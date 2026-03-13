# Python 版验收清单

## 自动化检查

在仓库根目录执行：

```bash
./kcomm --version
python3 -m py_compile kcomm.py
python3 -m unittest discover -s tests -v
```

当前自动化测试覆盖：

- kubeconfig 三种来源的合并、去重和绝对路径归一化
- kubeconfig `config view` JSON 到 context 列表的解析
- pod JSON 到 Python 数据结构的解析
- pod 选择标签在“指定 namespace / 全部 namespace”两种模式下的格式化
- Python 主入口包装与 CLI `--version` 行为
- 基于 mock `kubectl` 的主流程集成测试

## 人工验收路径

### 1. 单 kubeconfig 自动进入下一步

- 仅保留一个 kubeconfig
- 运行 `./kcomm`
- 预期：直接进入 context 选择，不出现 kubeconfig 选择界面

### 2. 多 kubeconfig 交互选择

- 准备 `~/.kube/config-list` 或 `~/.kube/configs`
- 运行 `./kcomm`
- 预期：先出现 kubeconfig 选择界面，选中后进入 context 选择

### 3. context 解析正确

- 使用包含多个 context 的 kubeconfig
- 运行 `./kcomm`
- 预期：context 列表能看到 `name | cluster | user | namespace`

### 4. namespace 范围正确

- 分别选择具体 namespace 和 `<全部命名空间>`
- 允许在 namespace 选择界面直接输入关键字过滤候选
- 预期：前者只展示该 namespace 的 pod，后者可跨 namespace 搜索 pod

### 5. pod 空结果提示准确

- 令 `POD_PHASE` 指向当前无结果的状态，例如：

```bash
POD_PHASE=Pending python3 ./kcomm.py
```

- 预期：具体 namespace 下显示“该 namespace 没有对应状态 pod”，全部命名空间下显示“当前集群没有对应状态 pod”

### 6. 多容器选择与回退

- 选择一个包含多个 container 的 pod
- 预期：出现容器选择界面
- 若跳过容器选择，预期：自动回退到第一个容器

### 7. shell 回退逻辑

- 分别选择一个有 `/bin/bash` 和一个只有 `/bin/sh` 的容器
- 预期：优先进入 `/bin/bash`；若不存在，则自动进入 `/bin/sh`

## 环境变量兼容性

- `KUBE_CONFIG_LIST`：可替代默认 config-list 路径
- `KUBE_CONFIGS_DIR`：可替代默认 configs 目录
- `POD_PHASE`：可改变 pod 过滤状态
- `FZF_OPTS`：Python 版会明确提示“已忽略”

## 备份入口

- `./kcomm.bash`：旧 Bash 实现，保留为备份与兼容
- `./kcomm.ps1`：旧 PowerShell 实现，保留为备份与兼容
