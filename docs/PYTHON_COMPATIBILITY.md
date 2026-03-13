# Python 版兼容清单

本文档用于约束 Python 主版 `kcomm` / `kcomm.py` 的行为边界，确保它与备份版 `kcomm.bash` / `kcomm.ps1` 在关键流程上保持一致。

## 必须保持一致的行为

- kubeconfig 来源仍按以下顺序合并：`KUBE_CONFIG_LIST` -> `KUBE_CONFIGS_DIR` -> `~/.kube/config`
- kubeconfig 路径统一转为绝对路径后再参与选择
- 只有一个 kubeconfig 时自动使用；多个时进入交互选择
- 所有 `kubectl` 调用都通过 `KUBECONFIG=<所选配置>` 和 `--context <所选 context>` 工作
- 不修改 kubeconfig 文件中的 `current-context`
- 先选择 namespace，再获取 pod 列表，避免大集群启动时拉取全量 pod
- 保留 `<全部命名空间>` 语义；选中后等价于 `kubectl get pods -A`
- 默认只展示 `Running` pod；可通过 `POD_PHASE` 覆盖
- pod 选择仍然是“输入关键字实时过滤”的交互模型
- 多容器 pod 需要二次选择容器；如果跳过选择，则回退到第一个容器
- 进入容器前先探测 `/bin/bash`，不存在时回退到 `/bin/sh`
- 错误信息要区分“无数据”和“权限 / 网络 / kubectl 调用失败”

## Python 版允许的差异

- 不再依赖 `fzf`，交互由 Python TUI 库完成
- `FZF_OPTS` 在 Python 版中不生效，但需要显式提示用户“已忽略”
- 不强制保留 Bash 版的 preview 窗口形式，只保留选择顺序和核心信息可见性
- 仓库根目录的 `kcomm` 现在是 Python 主入口；原 Bash 实现迁移到 `kcomm.bash`

## 验收重点

- 单一 kubeconfig 自动跳过第一步选择
- context 列表可从 kubeconfig 正确解析
- 指定 namespace 与全部 namespace 都能得到正确 pod 范围
- 空 namespace / 空 pod 列表时提示准确
- 多容器回退逻辑和 shell 回退逻辑符合 Bash 版行为
