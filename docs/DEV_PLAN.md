# K8s 容器连接工具 — 可行性分析与开发方案

## 一、需求摘要

1. **运行环境**：在 bash 命令行下运行
2. **配置选择**：启动时从已保存的 kube 配置中选择，支持 ↑/↓ 选择、回车确定
3. **Pod 选择**：输入关键字实时模糊匹配 Pod 名称，↑/↓ 选择、回车确定后进入容器 bash

---

## 二、可行性结论

**结论：完全可行。** 所需能力均有成熟实现方式：

| 能力           | 实现方式 |
|----------------|----------|
| 多 kubeconfig  | 多个文件（如 `~/.kube/configs/*.yaml`）或一份索引配置 |
| 交互式列表选择 | TUI 库（方向键 + 回车） |
| 实时模糊匹配   | 边输入边过滤列表，或交给 fzf 等工具 |
| 进入容器       | `kubectl exec -it <pod> -n <ns> -- /bin/bash`（或 sh） |

---

## 三、技术方案对比

### 方案 A：Bash + fzf（推荐用于快速落地）

- **思路**：用 shell 串联逻辑，用 **fzf** 做“选择配置”和“模糊选 Pod”。
- **优点**：
  - 依赖少（bash + kubectl + fzf），fzf 专为模糊选择设计，体验好
  - 实现快，易改易维护
  - 无需编译，改完即用
- **缺点**：
  - 多 kubeconfig 的“保存/管理”需约定目录或简单配置文件
  - 复杂交互（如多容器选择）要再写一层

**工具链**：Bash、kubectl、fzf（`apt install fzf` / `sudo snap install fzf`）

---

### 方案 B：Python + 交互库（推荐用于可扩展产品）

- **思路**：Python 主控，用 **questionary** 或 **InquirerPy** 做单选/列表，用 **prompt_toolkit** 或 **questionary** 的 autocomplete 做“输入 + 实时过滤 Pod”。
- **优点**：
  - 逻辑清晰，易加“命名空间选择、多容器选择、历史记录”等
  - 跨平台一致，不依赖 fzf
- **缺点**：
  - 需要 Python 3.8+ 和 pip 依赖

**工具链**：Python 3、questionary（或 InquirerPy）、prompt_toolkit（可选）

---

### 方案 C：Go + TUI 库（适合要单二进制分发）

- **思路**：用 **Bubble Tea** 或 **survey** 做交互，用 **cobra** 做子命令，通过 `exec.Command("kubectl", ...)` 或 **client-go** 调集群。
- **优点**：单二进制、无运行时依赖、性能好，适合内部分发。
- **缺点**：开发量最大，TUI 状态机要自己设计。

**工具链**：Go 1.21+、Bubble Tea（或 survey）、kubectl（或 client-go）

---

## 四、推荐路线与开发方案

### 阶段一：用 Bash + fzf 实现 MVP（优先推荐）

**目标**：最少依赖、最快能用，满足“选配置 → 模糊选 Pod → 进 bash”。

1. **kube 配置管理**
   - 约定目录：如 `~/.kube/configs/`，每个文件一个 kubeconfig（或一个“当前集群”）。
   - 或单文件索引：如 `~/.kube/config-list`，每行一个路径，由脚本读取并交给 fzf 选择。

2. **流程**
   ```
   启动
     → 用 fzf 从 config 列表选一个（可带预览：显示 current-context）
     → 导出 KUBECONFIG=所选文件
     → kubectl get pods -A -o "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name" 生成列表
     → 用 fzf 做“输入即模糊匹配”的 Pod 选择（可带预览：pod describe 或 get pod -o yaml）
     → 解析出 namespace + pod
     → 若 Pod 多容器，可再 fzf 选容器（或默认第一个）
     → 执行 kubectl exec -it <pod> -n <ns> [-c <container>] -- /bin/bash
   ```

3. **fzf 要点**
   - 配置选择：`cat ~/.kube/config-list | fzf --height=10 --prompt="Kubeconfig> "`
   - Pod 选择：`kubectl get pods -A ... | fzf --height=20 --bind "change:reload:kubectl get pods -A ..."` 较复杂，更简单做法是：一次性拉取“NAMESPACE Pod名”列表，用 fzf 的默认模糊匹配即可实现“输入关键字实时匹配”（fzf 自带）。

4. **交付物**
   - 一个主脚本：如 `kcomm` 或 `kexec`（可放在 `~/scripts/kcomm/` 或 PATH 下）。
   - 可选：`README` 说明如何配置 `~/.kube/configs/` 或 `config-list`。

**工具链**：Bash、kubectl、fzf。

---

### 阶段二（可选）：用 Python 做“增强版”

在阶段一验证流程后，若需要更好扩展性，再用 Python 重写或包装：

1. **配置选择**：questionary 的 `select()`，数据源同上（目录扫描或 config-list）。
2. **Pod 列表**：用 `subprocess` 调 `kubectl get pods -A -o json`，解析出 namespace + name。
3. **实时模糊**：用 questionary 的 `autocomplete` 或 `prompt_toolkit` 的 `FuzzyCompleter`，在用户输入时过滤 Pod 列表并刷新候选。
4. **执行**：`subprocess.run(["kubectl", "exec", "-it", pod, "-n", ns, "--", "/bin/bash"], env={**os.environ, "KUBECONFIG": chosen_config})`。

**工具链**：Python 3、questionary（或 InquirerPy）、prompt_toolkit（可选）。

---

## 五、开发计划（按阶段一）

| 步骤 | 内容 | 产出 |
|------|------|------|
| 1 | 约定 kubeconfig 存放方式（目录或 config-list） | 文档 + 示例目录/文件 |
| 2 | 实现“配置选择”：列出配置 → fzf 选择 → 设置 KUBECONFIG | 脚本片段/主脚本 |
| 3 | 实现“Pod 列表”：根据当前 KUBECONFIG 拉取 namespace+pod | 脚本片段 |
| 4 | 实现“Pod 选择”：fzf 模糊 + 回车解析 namespace/pod | 脚本片段 |
| 5 | 实现 exec：默认 /bin/bash，可选多容器选择 | 主脚本 |
| 6 | 错误处理（无配置、无 Pod、exec 失败）、README | 完整脚本 + 文档 |

---

## 六、风险与注意点

- **kubectl 未安装或不可用**：脚本开头检查 `command -v kubectl`，失败则提示安装。
- **fzf 未安装**：同上，提示 `apt install fzf` 或 `snap install fzf`。
- **列表很大**：Pod 很多时，可考虑“先选命名空间再选 Pod”或限制默认命名空间，减少首屏数据量。
- **Evicted/Not Running 的 Pod**：可在 `kubectl get pods` 时过滤掉 `Evicted`、`Error` 等，只展示 Running，避免误选。

---

## 七、小结

- **可行性**：高；选配置 + 模糊选 Pod + exec 进 bash 均可实现。
- **推荐先做**：Bash + fzf 的 MVP，再视需要做 Python 增强版或 Go 单二进制版。
- **工具链（阶段一）**：Bash、kubectl、fzf；可选依赖：jq（若用 JSON 解析 Pod 列表）。

如果你愿意从阶段一的脚本开始，我可以按你当前目录结构给出一份完整的 `kcomm` 脚本草稿（含配置选择 + Pod 模糊选择 + exec）。
