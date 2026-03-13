#!/usr/bin/env pwsh
#
# kcomm.ps1 - 通过 fzf 选择 kubeconfig 和 Pod，快速进入容器 bash
# PowerShell 7 版本
#

#Requires -Version 7.0

$script:KubeConfigsDir = if ($env:KUBE_CONFIGS_DIR) { $env:KUBE_CONFIGS_DIR } else { Join-Path $HOME '.kube' 'configs' }
$script:KubeConfigList = if ($env:KUBE_CONFIG_LIST) { $env:KUBE_CONFIG_LIST } else { Join-Path $HOME '.kube' 'config-list' }
$script:FzfOpts = if ($env:FZF_OPTS) { @($env:FZF_OPTS -split '\s+') } else { @('--height=15', '--layout=reverse') }
$script:PodPhase = if ($env:POD_PHASE) { $env:POD_PHASE } else { 'Running' }
# Windows 下 fzf preview 由 cmd 执行，需用 helper 接收 {q} 参数避免命令注入
$script:PreviewHelper = $null

function Initialize-PreviewHelper {
    if (-not $IsWindows -or $script:PreviewHelper) { return }
    $script:PreviewHelper = [System.IO.Path]::GetTempFileName() + '.ps1'
    @'
param($Mode, $Line)
if ($Mode -eq 'kubeconfig') {
    $env:KUBECONFIG = $Line
    & kubectl config current-context 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host '无效或无法读取' }
} elseif ($Mode -eq 'context') {
    & kubectl config view --minify --context $Line -o yaml 2>$null | Select-Object -First 50
} elseif ($Mode -eq 'pod') {
    $parts = $Line.Trim() -split '\s+', 2
    if ($parts.Count -ge 2) {
        & kubectl --context $env:KCOMM_CTX get pod -n $parts[0] $parts[1] -o wide 2>$null
    }
}
'@ | Set-Content -LiteralPath $script:PreviewHelper -Encoding UTF8
}

function Exit-WithError([string]$Message) {
    [Console]::Error.WriteLine("kcomm: $Message")
    exit 1
}

function Test-Dependencies {
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        Exit-WithError '未找到 kubectl，请先安装（winget install Kubernetes.kubectl）'
    }
    if (-not (Get-Command fzf -ErrorAction SilentlyContinue)) {
        Exit-WithError '未找到 fzf，请先安装（winget install fzf / scoop install fzf / choco install fzf）'
    }
}

# 生成可选的 kubeconfig 列表：config-list 文件 + configs 目录 + 默认 config，去重
function Build-ConfigList {
    $list = [System.Collections.Generic.List[string]]::new()

    if (Test-Path $script:KubeConfigList -PathType Leaf) {
        foreach ($line in Get-Content $script:KubeConfigList) {
            if ($line -notmatch '^\s*#' -and $line -notmatch '^\s*$') {
                $list.Add($line.Trim())
            }
        }
    }

    if (Test-Path $script:KubeConfigsDir -PathType Container) {
        Get-ChildItem $script:KubeConfigsDir -File |
            Where-Object { $_.Name -match '\.(ya?ml)$' -or $_.Name -eq 'config' } |
            Sort-Object Name |
            ForEach-Object { $list.Add($_.FullName) }
    }

    $defaultCfg = Join-Path $HOME '.kube' 'config'
    if (Test-Path $defaultCfg -PathType Leaf) {
        $list.Add((Resolve-Path $defaultCfg).Path)
    }

    @($list | Sort-Object -Unique)
}

# 选择 kubeconfig：仅当存在多个配置时交互选择
function Select-Kubeconfig {
    $list = @(Build-ConfigList)
    if ($list.Count -eq 0) {
        Exit-WithError "未找到任何 kubeconfig。可创建目录 $script:KubeConfigsDir 并放入 .yaml 配置文件，或创建 $script:KubeConfigList 每行一个路径。"
    }

    if ($list.Count -eq 1) {
        $resolved = Resolve-Path $list[0] -ErrorAction SilentlyContinue
        return $resolved ? $resolved.Path : $list[0]
    }

    if ($IsWindows) {
        Initialize-PreviewHelper
        $preview = "pwsh -NoProfile -File `"$script:PreviewHelper`" -Mode kubeconfig -Line {q}"
    }
    else {
        $preview = 'KUBECONFIG={q} kubectl config current-context 2>/dev/null || echo "无效或无法读取"'
    }

    $chosen = $list | fzf @script:FzfOpts --prompt='Kubeconfig> ' --preview $preview --preview-window='right:40%'
    if (-not $chosen) { Exit-WithError '未选择配置，已退出' }

    $resolved = Resolve-Path $chosen -ErrorAction SilentlyContinue
    if ($resolved) { return $resolved.Path } else { return $chosen }
}

# 从 kubeconfig 解析并列出所有 context 名称
function Get-ContextList([string]$Kubeconfig) {
    $env:KUBECONFIG = $Kubeconfig
    $raw = kubectl config view -o 'jsonpath={.contexts[*].name}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return @() }
    @(($raw -join '') -split '\s+' | Where-Object { $_ })
}

# 选择 context（集群环境）
function Select-Context([string]$Kubeconfig) {
    $env:KUBECONFIG = $Kubeconfig
    $list = @(Get-ContextList $Kubeconfig)
    if ($list.Count -eq 0) {
        Exit-WithError "该 kubeconfig ($Kubeconfig) 中未找到任何 context，或无法解析。请确认：1) 文件路径正确 2) 文件内含 contexts 段。"
    }

    if ($IsWindows) {
        Initialize-PreviewHelper
        $preview = "pwsh -NoProfile -File `"$script:PreviewHelper`" -Mode context -Line {q}"
    }
    else {
        $preview = 'kubectl config view --minify --context={q} -o yaml 2>/dev/null | head -50'
    }

    $chosen = $list | fzf @script:FzfOpts --prompt='Context (集群环境)> ' --preview $preview --preview-window='right:55%'
    if (-not $chosen) { Exit-WithError '未选择集群环境，已退出' }
    return $chosen
}

# 获取 Pod 列表：仅 Running，使用 custom-columns 避免大 JSON 解析问题
function Get-PodList([string]$Kubeconfig, [string]$Context) {
    $env:KUBECONFIG = $Kubeconfig
    $raw = kubectl --context=$Context get pods -A `
        --field-selector="status.phase=$script:PodPhase" `
        -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name' `
        --no-headers 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return @() }
    @($raw | Where-Object { $_ -match '\S' } | ForEach-Object {
        $parts = $_ -split '\s+', 2
        "$($parts[0])`t$($parts[1])"
    })
}

# 选择 Pod：fzf 模糊匹配
function Select-Pod([string]$Kubeconfig, [string]$Context) {
    $list = @(Get-PodList $Kubeconfig $Context)
    if ($list.Count -eq 0) {
        Exit-WithError '当前集群没有 Running 状态的 Pod，或无法访问集群（请检查 KUBECONFIG、context 与网络）。'
    }

    $formatted = $list | ForEach-Object {
        $parts = $_ -split "`t", 2
        '{0,-32} {1}' -f $parts[0], $parts[1]
    }

    $env:KCOMM_CTX = $Context
    if ($IsWindows) {
        Initialize-PreviewHelper
        $preview = "pwsh -NoProfile -File `"$script:PreviewHelper`" -Mode pod -Line {q}"
    }
    else {
        # 使用 {q} 将当前行以 shell 转义形式传入，在 preview 内解析为 ns/pod 再调用 kubectl，避免命令注入
        $preview = 'set -- {q}; ns="${1%% *}"; pod="${1#* }"; pod="${pod# }"; kubectl --context="$KCOMM_CTX" get pod -n "$ns" "$pod" -o wide 2>/dev/null || true'
    }

    $chosen = $formatted | fzf @script:FzfOpts --prompt='Pod (输入关键字模糊匹配)> ' --preview $preview --preview-window='right:60%'
    if (-not $chosen) { Exit-WithError '未选择 Pod，已退出' }

    $parts = $chosen.Trim() -split '\s+', 2
    @{ Namespace = $parts[0]; Pod = $parts[1] }
}

# 若 Pod 多容器，用 fzf 选一个，否则返回第一个容器名
function Select-Container([string]$Kubeconfig, [string]$Context, [string]$Namespace, [string]$Pod) {
    $env:KUBECONFIG = $Kubeconfig
    $containerStr = kubectl --context=$Context get pod -n $Namespace $Pod `
        -o 'jsonpath={.spec.containers[*].name}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $containerStr) { return $null }
    $containers = @($containerStr -split '\s+' | Where-Object { $_ })

    if ($containers.Count -le 1) { return $containers[0] }

    $chosen = $containers | fzf @script:FzfOpts --prompt='容器> '
    if (-not $chosen) { return $containers[0] }
    return $chosen
}

# 进入容器：优先 bash，失败则 sh
function Enter-Pod([string]$Kubeconfig, [string]$Context, [string]$Namespace, [string]$Pod, [string]$Container) {
    $env:KUBECONFIG = $Kubeconfig
    $extraArgs = if ($Container) { @('-c', $Container) } else { @() }

    kubectl --context=$Context exec -it -n $Namespace $Pod @extraArgs -- /bin/bash 2>$null
    if ($LASTEXITCODE -eq 126 -or $LASTEXITCODE -eq 127) {
        kubectl --context=$Context exec -it -n $Namespace $Pod @extraArgs -- /bin/sh
    }
}

# ── 主流程 ──

Test-Dependencies

$kconfig = Select-Kubeconfig
$env:KUBECONFIG = $kconfig

$ctx = Select-Context $kconfig

$podInfo = Select-Pod $kconfig $ctx

$container = Select-Container $kconfig $ctx $podInfo.Namespace $podInfo.Pod

Enter-Pod $kconfig $ctx $podInfo.Namespace $podInfo.Pod $container
