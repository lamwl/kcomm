# kcomm

在终端里用 **fzf** 选择 kubeconfig、集群环境（context）和 Pod，快速进入 Kubernetes 容器 bash。

- 启动时从已保存的 kube 配置中选择（↑/↓ 选择，回车确定）
- **通过解析 kubeconfig 内容选择集群环境**：同一 config 中可包含多个 context，用 fzf 选择要连接的集群（↑/↓ 选择，回车确定）
- 输入关键字实时模糊匹配 Pod 名称（↑/↓ 选择，回车确定）
- 多容器 Pod 会再提示选择容器
- 自动进入容器内 bash（无 bash 则 fallback 到 sh）

提供两个版本：**Bash 版**（Linux / macOS）和 **PowerShell 7 版**（Windows / 跨平台）。

## 依赖

### Bash 版（`kcomm`）

- **bash**
- **kubectl**（例如：`sudo snap install kubectl --classic`）
- **fzf**（例如：`sudo apt install fzf` 或 `sudo snap install fzf`）

### PowerShell 7 版（`kcomm.ps1`）

- **PowerShell 7+**（`winget install Microsoft.PowerShell`）
- **kubectl**（`winget install Kubernetes.kubectl`）
- **fzf**（`winget install fzf` / `scoop install fzf` / `choco install fzf`）

## 安装 / 使用

### Bash 版（Linux / macOS）

```bash
# 赋予执行权限（若尚未）
chmod +x /path/to/kcomm

# 直接运行（或把所在目录加入 PATH 后执行 kcomm）
./kcomm
```

建议把脚本放到 PATH 下或做软链，例如：

```bash
sudo ln -sf "$(pwd)/kcomm" /usr/local/bin/kcomm
```

### PowerShell 7 版（Windows / 跨平台）

```powershell
# 直接运行
pwsh -File ./kcomm.ps1

# 或在 PowerShell 7 会话中
./kcomm.ps1
```

若遇到执行策略限制，可临时放行：

```powershell
pwsh -ExecutionPolicy Bypass -File ./kcomm.ps1
```

建议将脚本所在目录加入 `$env:PATH`，或创建 PowerShell profile 别名：

```powershell
# 在 $PROFILE 中添加
Set-Alias kcomm 'C:\path\to\kcomm.ps1'
```

## 配置 kubeconfig 来源

脚本按以下顺序查找可选的 kubeconfig，并合并为列表供选择：

1. **配置文件列表**（推荐）  
   若存在 `~/.kube/config-list`，则读取其中每行一个路径（支持 `#` 注释和空行）：
   ```
   # 生产
   /home/you/.kube/configs/prod.yaml
   # 测试
   /home/you/.kube/configs/test.yaml
   ```

2. **配置目录**  
   若存在目录 `~/.kube/configs/`，则列出其中的 `*.yaml`、`*.yml` 及名为 `config` 的文件。

3. **默认 config**  
   若存在 `~/.kube/config`，会加入列表。

可通过环境变量覆盖路径（可选）：

- `KUBE_CONFIG_LIST`：替代 `~/.kube/config-list`
- `KUBE_CONFIGS_DIR`：替代 `~/.kube/configs`
- `FZF_OPTS`：传给 fzf 的额外参数（默认 `--height=15 --layout=reverse`）
- `POD_PHASE`：只列哪种状态的 Pod（默认 `Running`）

## 使用流程

1. 运行 `kcomm`
2. 若有多个 kubeconfig，在第一个 fzf 中选择一个 **kubeconfig**（否则自动使用唯一配置）
3. 在 **Context（集群环境）** fzf 中从该 config 解析出的所有 context 里选一个（列：NAME / CLUSTER / USER / NAMESPACE，右侧可预览该 context 的 yaml）
4. 在 **Pod** fzf 中**输入关键字**模糊匹配该集群下的 Pod，选中后回车（右侧预览为 `kubectl get pod -o wide`）
5. 若该 Pod 有多个容器，再在 fzf 中选择 **容器**
6. 脚本执行 `kubectl exec -it ... -- /bin/bash`（失败则尝试 `/bin/sh`），进入容器 shell

所有 kubectl 操作均使用所选 context，**不会修改** kubeconfig 文件中的 current-context。

## 示例

### Bash 版

```bash
# 使用默认路径
./kcomm

# 使用自定义 config 目录
KUBE_CONFIGS_DIR=~/my-kube-configs ./kcomm

# 调整 fzf 高度
FZF_OPTS="--height=20 --layout=reverse" ./kcomm
```

### PowerShell 7 版

```powershell
# 使用默认路径
./kcomm.ps1

# 使用自定义 config 目录
$env:KUBE_CONFIGS_DIR = "$HOME\my-kube-configs"; ./kcomm.ps1

# 调整 fzf 高度
$env:FZF_OPTS = '--height=20 --layout=reverse'; ./kcomm.ps1
```

## 方案说明

- Bash 版对应文档中的 **方案 A（Bash + fzf）**
- PowerShell 7 版为 Bash 版的跨平台移植，功能完全一致

详见 [docs/DEV_PLAN.md](docs/DEV_PLAN.md)。
