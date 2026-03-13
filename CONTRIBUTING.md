# Contributing to kcomm

感谢你对 `kcomm` 的关注和贡献。

## 开发准备

1. 安装 Python 3.8+。
2. 在仓库根目录执行可编辑安装：

```bash
python3 -m pip install -e .
```

3. 如需实际运行主功能，请确保本机已安装 `kubectl`，并准备可访问的 kubeconfig。

## 运行测试

请在提交前执行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

说明：

- 直接执行 `python3 -m unittest` 可能无法自动发现当前仓库测试。
- 当前测试主要覆盖核心解析逻辑、命令入口和 mock kubectl 集成流程。

## 提交建议

- 保持改动聚焦，避免一次提交混入无关修改。
- 如修改 CLI 行为、参数、安装方式或文档示例，请同步更新 `README.md`。
- 如新增功能或修复缺陷，请补充或更新对应测试。
- 保持与现有代码风格一致，优先选择简单、可维护的实现。

## Issue 和 Pull Request

- 提交 Issue 时，请尽量提供操作系统、Python 版本、`kubectl` 版本、复现步骤和实际报错。
- 提交 Pull Request 时，请简要说明改动目的、主要变更和测试结果。

感谢你的帮助。
