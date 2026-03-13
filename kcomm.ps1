#!/usr/bin/env pwsh
#
# kcomm.ps1 - 通过 fzf 选择 kubeconfig 和 Pod，快速进入容器 bash
# PowerShell 7 备份版，保留用于兼容场景
#

#Requires -Version 7.0

$script:KubeConfigsDir = if ($env:KUBE_CONFIGS_DIR) { $env:KUBE_CONFIGS_DIR } else { Join-Path $HOME '.kube' 'configs' }
$script:KubeConfigList = if ($env:KUBE_CONFIG_LIST) { $env:KUBE_CONFIG_LIST } else { Join-Path $HOME '.kube' 'config-list' }
$script:FzfOpts = if ($env:FZF_OPTS) { @($env:FZF_OPTS -split '\s+') } else { @('--height=15', '--layout=reverse') }
$script:PodPhase = if ($env:POD_PHASE) { $env:POD_PHASE } else { 'Running' }
# Windows 下 fzf preview 由 cmd 执行，需用 helper 接收当前行内容
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
} elseif ($Mode -eq 'pod-single-ns' -or $Mode -eq 'pod-all-ns') {
    $parts = $Line -split "`t", 5
    if ($parts.Count -ge 5) {
        if ($Mode -eq 'pod-all-ns') {
            Write-Host "命名空间: $($parts[0])"
        }
        Write-Host "Pod: $($parts[1])"
        Write-Host "状态: $(if ($parts[2]) { $parts[2] } else { '-' })"
        Write-Host "启动时间: $(if ($parts[3]) { $parts[3] } else { '-' })"
        Write-Host "Pod IP: $(if ($parts[4]) { $parts[4] } else { '-' })"
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

# 获取命名空间列表（使用指定 context）
function Get-NamespaceList([string]$Kubeconfig, [string]$Context) {
    $env:KUBECONFIG = $Kubeconfig
    $raw = kubectl --context=$Context get namespaces -o jsonpath='{.items[*].metadata.name}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return @() }
    @($raw -split '\s+' | Where-Object { $_ })
}

# 选择命名空间：此阶段仅选择 namespace，不查询 Pod；确定后再拉取 Pod 列表
function Select-Namespace([string]$Kubeconfig, [string]$Context) {
    $env:KUBECONFIG = $Kubeconfig
    $list = @(Get-NamespaceList $Kubeconfig $Context)
    if ($list.Count -eq 0) {
        $err = kubectl --context=$Context get namespaces --request-timeout=10s 2>&1
        if ($LASTEXITCODE -ne 0) {
            $errTrim = if ($err.Length -gt 350) { $err.Substring(0, 350) + '...' } else { $err }
            Exit-WithError "无法获取命名空间列表（权限或网络）。kubectl 输出: $errTrim"
        }
        Exit-WithError '未找到任何命名空间。'
    }
    $fullList = @('<全部命名空间>') + @($list)
    $preview = 'echo 仅选择命名空间，确认后再查询 Pod 列表'
    $chosen = $fullList | fzf @script:FzfOpts --prompt='Namespace (命名空间)> ' --preview $preview --preview-window=right:50%
    if (-not $chosen) { Exit-WithError '未选择命名空间，已退出' }
    if ($chosen -eq '<全部命名空间>') { return '' }
    return $chosen
}

# 获取 Pod 列表：仅 Running；返回 namespace、pod、status、startTime、podIP
function Get-PodList([string]$Kubeconfig, [string]$Context, [string]$Namespace) {
    $env:KUBECONFIG = $Kubeconfig
    $nsArg = if ($Namespace) { @('-n', $Namespace) } else { @('-A') }
    $raw = kubectl --context=$Context get pods @nsArg `
        --field-selector="status.phase=$script:PodPhase" `
        -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,START_TIME:.status.startTime,POD_IP:.status.podIP' `
        --no-headers 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return @() }
    @($raw | Where-Object { $_ -match '\S' } | ForEach-Object {
        $parts = $_ -split '\s+', 5
        $namespace = if ($parts.Count -ge 1) { $parts[0] } else { '' }
        $pod = if ($parts.Count -ge 2) { $parts[1] } else { '' }
        $status = if ($parts.Count -ge 3) { $parts[2] } else { '' }
        $startTime = if ($parts.Count -ge 4) { $parts[3] } else { '' }
        $podIp = if ($parts.Count -ge 5) { $parts[4] } else { '' }
        "$namespace`t$pod`t$status`t$startTime`t$podIp"
    })
}

# 选择 Pod：全部命名空间时 preview 展示 namespace；指定命名空间时不展示
function Select-Pod([string]$Kubeconfig, [string]$Context, [string]$Namespace) {
    $list = @(Get-PodList $Kubeconfig $Context $Namespace)
    if ($list.Count -eq 0) {
        # 区分「无 Pod」与「集群不可达/无权限」：重新执行并捕获 stderr 与退出码
        $env:KUBECONFIG = $Kubeconfig
        $nsArgs = if ($Namespace) { @('-n', $Namespace) } else { @('-A') }
        $err = kubectl --context=$Context get pods @nsArgs `
            --field-selector="status.phase=$script:PodPhase" `
            --request-timeout=10s `
            -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,START_TIME:.status.startTime,POD_IP:.status.podIP' `
            --no-headers 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $errTrim = if ($err.Length -gt 450) { $err.Substring(0, 450) + '...' } else { $err }
            Exit-WithError "无法访问集群或没有权限（kubectl 退出码 $exitCode）。请检查 KUBECONFIG、context、网络与 RBAC。kubectl 输出: $errTrim"
        }
        if ($Namespace) {
            Exit-WithError "命名空间 `"$Namespace`" 下没有 $script:PodPhase 状态的 Pod。"
        }
        else {
            Exit-WithError "当前集群没有 $script:PodPhase 状态的 Pod。"
        }
    }

    if ($Namespace) {
        $preview = if ($IsWindows) {
            Initialize-PreviewHelper
            "pwsh -NoProfile -File `"$script:PreviewHelper`" -Mode pod-single-ns -Line ""{}"""
        }
        else {
            'printf "%s\n" {} | awk -F "\t" "{printf \"Pod: %s\n状态: %s\n启动时间: %s\nPod IP: %s\n\", \$2, (\$3 != \"\" ? \$3 : \"-\"), (\$4 != \"\" ? \$4 : \"-\"), (\$5 != \"\" ? \$5 : \"-\")}"'
        }
    }
    else {
        $preview = if ($IsWindows) {
            Initialize-PreviewHelper
            "pwsh -NoProfile -File `"$script:PreviewHelper`" -Mode pod-all-ns -Line ""{}"""
        }
        else {
            'printf "%s\n" {} | awk -F "\t" "{printf \"命名空间: %s\nPod: %s\n状态: %s\n启动时间: %s\nPod IP: %s\n\", \$1, \$2, (\$3 != \"\" ? \$3 : \"-\"), (\$4 != \"\" ? \$4 : \"-\"), (\$5 != \"\" ? \$5 : \"-\")}"'
        }
    }

    $chosen = $list | fzf @script:FzfOpts --prompt='Pod (输入关键字模糊匹配)> ' --delimiter="`t" --with-nth='2,3,4,5' --preview $preview --preview-window='right:60%'
    if (-not $chosen) { Exit-WithError '未选择 Pod，已退出' }

    $parts = $chosen -split "`t", 5
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

# 进入容器：仅在确认没有 /bin/bash 时才回退到 sh
function Enter-Pod([string]$Kubeconfig, [string]$Context, [string]$Namespace, [string]$Pod, [string]$Container) {
    $env:KUBECONFIG = $Kubeconfig
    $extraArgs = if ($Container) { @('-c', $Container) } else { @() }

    kubectl --context=$Context exec -n $Namespace $Pod @extraArgs -- test -x /bin/bash *> $null
    if ($LASTEXITCODE -eq 0) {
        kubectl --context=$Context exec -it -n $Namespace $Pod @extraArgs -- /bin/bash
    }
    else {
        kubectl --context=$Context exec -it -n $Namespace $Pod @extraArgs -- /bin/sh
    }
}

# ── 主流程 ──

Test-Dependencies

$kconfig = Select-Kubeconfig
$env:KUBECONFIG = $kconfig

$ctx = Select-Context $kconfig

# 先选命名空间，大集群下避免一次性拉全量 Pod
$selectedNs = Select-Namespace $kconfig $ctx

$podInfo = Select-Pod $kconfig $ctx $selectedNs

$container = Select-Container $kconfig $ctx $podInfo.Namespace $podInfo.Pod

Enter-Pod $kconfig $ctx $podInfo.Namespace $podInfo.Pod $container
