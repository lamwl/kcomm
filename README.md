# kcomm

[![CI](https://github.com/lamwl/kcomm/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/lamwl/kcomm/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)

在终端里用交互式选择 kubeconfig、集群环境（context）和 Pod，快速进入 Kubernetes 容器 bash。

- 启动时从已保存的 kube 配置中选择（↑/↓ 选择，回车确定）
- **通过解析 kubeconfig 内容选择集群环境**：同一 config 中可包含多个 context，交互选择要连接的集群（↑/↓ 选择，回车确定）
- 输入关键字实时模糊匹配 Pod 名称（↑/↓ 选择，回车确定）
- 多容器 Pod 会再提示选择容器
- 自动进入容器内 bash（无 bash 则 fallback 到 sh）

当前提供三个入口，其中 **Python 3 版为主实现**：

- **Python 3 主入口**：`kcomm` / `src/kcomm/cli.py`
- **Bash 备份版**（Linux / macOS）：`kcomm.bash`
- **PowerShell 7 备份版**（Windows / 跨平台）：`kcomm.ps1`

## 依赖

### Python 3 主版（`kcomm` / `src/kcomm/cli.py`）

- **Python 3.8+**
- **kubectl**
- **InquirerPy**（推荐通过 `pip install InquirerPy`，或按 `pyproject.toml` 安装）

### Bash 备份版（`kcomm.bash`）

- **bash**
- **kubectl**（例如：`sudo snap install kubectl --classic`）
- **fzf**（例如：`sudo apt install fzf` 或 `sudo snap install fzf`）

### PowerShell 7 备份版（`kcomm.ps1`）

- **PowerShell 7+**（`winget install Microsoft.PowerShell`）
- **kubectl**（`winget install Kubernetes.kubectl`）
- **fzf**（`winget install fzf` / `scoop install fzf` / `choco install fzf`）

## 安装 / 使用

### Python 3 主版

```bash
# 仓库内直接运行主入口
./kcomm

# 或直接运行兼容入口文件
python3 ./kcomm.py

# 安装为正式 CLI 命令
python3 -m pip install .
kcomm
```

### 安装方式

#### 用 pip 本地安装

```bash
# 在仓库根目录安装到当前 Python 环境
python3 -m pip install .

# 可编辑安装，适合开发时边改边用
python3 -m pip install -e .
```

#### 用 pipx 安装为独立 CLI

```bash
# 若尚未安装 pipx
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# 在仓库根目录安装当前项目
pipx install .

# 如果已经安装过，重新安装当前源码
pipx reinstall .

# 查看命令是否可用
kcomm --version
```

#### 发布后的安装方式

如果后续发布到包仓库，可直接安装：

```bash
pipx install kcomm
# 或
python3 -m pip install kcomm
```

#### 卸载

```bash
pipx uninstall kcomm
# 或
python3 -m pip uninstall kcomm
```

### Bash 备份版（Linux / macOS）

```bash
# 直接运行备份版
./kcomm.bash
```

### PowerShell 7 备份版（Windows / 跨平台）

```powershell
# 直接运行备份版
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

说明：

- Bash / PowerShell 版会使用 `FZF_OPTS`
- Python 版不依赖 fzf，因此会显式忽略 `FZF_OPTS`

## 使用流程

1. 运行 `kcomm`
2. 若有多个 kubeconfig，在第一个交互列表中选择一个 **kubeconfig**（否则自动使用唯一配置）
3. 在 **Context（集群环境）** 列表中从该 config 解析出的所有 context 里选一个（Bash / PowerShell 备份版为 fzf；Python 主版展示同样的核心字段）
4. 在 **Namespace（命名空间）** 列表中选择一个命名空间，支持输入关键字过滤（首项为「全部命名空间」，选则后续列出全集群 Pod；选具体 ns 则只拉该 ns 的 Pod，大集群下更快）
5. 在 **Pod** 选择中**输入关键字**模糊匹配 Pod，选中后回车
6. 若该 Pod 有多个容器，再在交互列表中选择 **容器**
7. 脚本执行 `kubectl exec -it ... -- /bin/bash`（失败则尝试 `/bin/sh`），进入容器 shell

所有 kubectl 操作均使用所选 context，**不会修改** kubeconfig 文件中的 current-context。

## 示例

### Python 3 主版

```bash
# 使用默认路径
./kcomm

# 使用自定义 config 目录
KUBE_CONFIGS_DIR=~/my-kube-configs ./kcomm

# 指定展示 Pod 状态
POD_PHASE=Pending ./kcomm
```

### Bash 备份版

```bash
# 使用默认路径
./kcomm.bash

# 使用自定义 config 目录
KUBE_CONFIGS_DIR=~/my-kube-configs ./kcomm.bash

# 调整 fzf 高度
FZF_OPTS="--height=20 --layout=reverse" ./kcomm.bash
```

### PowerShell 7 备份版

```powershell
# 使用默认路径
./kcomm.ps1

# 使用自定义 config 目录
$env:KUBE_CONFIGS_DIR = "$HOME\my-kube-configs"; ./kcomm.ps1

# 调整 fzf 高度
$env:FZF_OPTS = '--height=20 --layout=reverse'; ./kcomm.ps1
```

### Python 文件兼容入口

```bash
# 使用默认路径
python3 ./kcomm.py

# 使用自定义 config 目录
KUBE_CONFIGS_DIR=~/my-kube-configs python3 ./kcomm.py

# 指定展示 Pod 状态
POD_PHASE=Pending python3 ./kcomm.py
```

## 方案说明

- Python 3 版现在是项目主实现，对外主命令为 `kcomm`
- Python 源码现采用更标准的 `src` 布局，主逻辑位于 `src/kcomm/cli.py`
- `kcomm.py` 仅保留为最小兼容入口，只负责转发到包内 `main()`
- Bash 版保留在 `kcomm.bash`，用于备份与兼容
- PowerShell 7 版保留在 `kcomm.ps1`，用于备份与兼容
- Bash / PowerShell 备份版对应文档中的 **方案 A（Bash + fzf）**
- Python 3 主版对应文档中的“阶段二增强版”，保持相同的选择顺序与 `kubectl` 行为，但交互界面由 `InquirerPy` 提供，不再依赖 `fzf`

详见 [docs/DEV_PLAN.md](docs/DEV_PLAN.md)。

## 开发 / 测试

开发时建议在仓库根目录使用可编辑安装：

```bash
python3 -m pip install -e .
```

运行测试请显式使用 `discover` 指向 `tests/` 目录：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

说明：

- 直接执行 `python3 -m unittest` 可能无法自动发现当前项目测试
- 当前测试覆盖核心解析逻辑、包装入口和基于 mock kubectl 的集成流程

## License

本项目基于 [MIT License](LICENSE) 开源。
