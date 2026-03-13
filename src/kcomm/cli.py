#!/usr/bin/env python3
"""
kcomm - 纯 Python 3 交互版 kcomm

保持与现有 Bash / PowerShell 实现尽量一致：
- 合并 kubeconfig 来源并选择
- 解析并选择 context
- 先选 namespace，再获取 Pod
- 模糊匹配 Pod
- 多容器时再选择 container
- 优先进入 /bin/bash，不存在时回退到 /bin/sh
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import __version__


DEFAULT_CONFIGS_DIR = ".kube/configs"
DEFAULT_CONFIG_LIST = ".kube/config-list"
DEFAULT_CONFIG = ".kube/config"
DEFAULT_POD_PHASE = "Running"
ALL_NAMESPACES_LABEL = "<全部命名空间>"
CLI_VERSION = __version__
FILTERED_KUBECTL_STDERR_PATTERN = re.compile(
    r"memcache\.go:\d+\].*custom\.metrics\.k8s\.io/v1beta1"
)


class KcommError(RuntimeError):
    """用于向用户输出友好的错误信息。"""


@dataclass(frozen=True)
class ContextInfo:
    name: str
    cluster: str
    user: str
    namespace: str


@dataclass(frozen=True)
class PodInfo:
    namespace: str
    name: str
    status: str
    start_time: str
    pod_ip: str


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        parse_args(argv)
        check_dependencies()
        warn_ignored_fzf_opts()

        kubeconfig = select_kubeconfig(build_config_list())
        contexts = get_contexts(kubeconfig)
        context = select_context(contexts)

        namespace = select_namespace(get_namespaces(kubeconfig, context.name))
        pods = get_pods(kubeconfig, context.name, namespace, pod_phase())
        pod = select_pod(namespace, pods)

        container = select_container(
            get_containers(kubeconfig, context.name, pod.namespace, pod.name)
        )
        return exec_into_pod(
            kubeconfig=kubeconfig,
            context=context.name,
            namespace=pod.namespace,
            pod=pod.name,
            container=container,
        )
    except KeyboardInterrupt:
        print("kcomm: 已退出", file=sys.stderr)
        return 130
    except KcommError as exc:
        print(f"kcomm: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kcomm",
        description="交互式选择 kubeconfig、context、namespace 和 pod，并进入容器 shell。",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args(list(argv) if argv is not None else None)


def pod_phase() -> str:
    return os.environ.get("POD_PHASE", DEFAULT_POD_PHASE)


def check_dependencies() -> None:
    if shutil.which("kubectl") is None:
        raise KcommError("未找到 kubectl，请先安装并确保它在 PATH 中。")


def warn_ignored_fzf_opts() -> None:
    if os.environ.get("FZF_OPTS"):
        print(
            "kcomm: Python 版不使用 fzf，已忽略环境变量 FZF_OPTS。",
            file=sys.stderr,
        )


def build_config_list(
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> List[str]:
    env = os.environ if env is None else env
    home = home or Path.home()

    config_list_path = kube_config_list_path(env, home)
    configs_dir = kube_configs_dir_path(env, home)
    default_config = default_kubeconfig_path(home)

    candidates = []
    candidates.extend(read_config_list_entries(config_list_path))
    candidates.extend(read_configs_dir_entries(configs_dir))
    candidates.extend(read_default_config_entry(default_config))

    unique = sorted(set(candidates))
    if not unique:
        raise KcommError(
            "未找到任何 kubeconfig。可创建 ~/.kube/configs 并放入 .yaml 配置，"
            "或创建 ~/.kube/config-list 每行一个路径。"
        )
    return unique


def kube_config_list_path(env: Mapping[str, str], home: Path) -> Path:
    return Path(
        env.get("KUBE_CONFIG_LIST", str(home / DEFAULT_CONFIG_LIST))
    ).expanduser()


def kube_configs_dir_path(env: Mapping[str, str], home: Path) -> Path:
    return Path(
        env.get("KUBE_CONFIGS_DIR", str(home / DEFAULT_CONFIGS_DIR))
    ).expanduser()


def default_kubeconfig_path(home: Path) -> Path:
    return (home / DEFAULT_CONFIG).expanduser()


def read_config_list_entries(config_list_path: Path) -> List[str]:
    if not config_list_path.is_file():
        return []

    entries: List[str] = []
    for line in config_list_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(normalize_path(stripped))
    return entries


def read_configs_dir_entries(configs_dir: Path) -> List[str]:
    if not configs_dir.is_dir():
        return []

    entries: List[str] = []
    for child in sorted(configs_dir.iterdir(), key=lambda item: item.name):
        if not child.is_file():
            continue
        if child.suffix in {".yaml", ".yml"} or child.name == "config":
            entries.append(normalize_path(str(child)))
    return entries


def read_default_config_entry(default_config: Path) -> List[str]:
    if not default_config.is_file():
        return []
    return [normalize_path(str(default_config))]


def normalize_path(raw_path: str) -> str:
    return str(Path(raw_path).expanduser().resolve(strict=False))


def select_kubeconfig(configs: Sequence[str]) -> str:
    if len(configs) == 1:
        return configs[0]

    choices = [{"name": path, "value": path} for path in configs]
    chosen = prompt_select("Kubeconfig> ", choices)
    if not chosen:
        raise KcommError("未选择配置，已退出")
    return str(chosen)


def get_contexts(kubeconfig: str) -> List[ContextInfo]:
    result = run_kubectl(
        kubeconfig,
        ["config", "view", "-o", "json"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise KcommError(
            "无法解析 kubeconfig，请确认文件路径和内容有效。"
            f" kubectl 输出: {trim_error(result.stderr, 200)}"
        )

    contexts = parse_contexts_from_config_view(result.stdout)
    if not contexts:
        raise KcommError("该 kubeconfig 中未找到任何 context，或无法解析。")
    return contexts


def parse_contexts_from_config_view(raw_json: str) -> List[ContextInfo]:
    payload = json.loads(raw_json or "{}")
    items = payload.get("contexts") or []
    contexts: List[ContextInfo] = []
    for item in items:
        info = item.get("context") or {}
        contexts.append(
            ContextInfo(
                name=item.get("name", ""),
                cluster=info.get("cluster", ""),
                user=info.get("user", ""),
                namespace=info.get("namespace", ""),
            )
        )
    return contexts


def select_context(contexts: Sequence[ContextInfo]) -> ContextInfo:
    choices = []
    for context in contexts:
        label = " | ".join(
            [
                context.name or "-",
                context.cluster or "-",
                context.user or "-",
                context.namespace or "-",
            ]
        )
        choices.append({"name": label, "value": context})

    chosen = prompt_select("Context (集群环境)> ", choices)
    if chosen is None:
        raise KcommError("未选择集群环境，已退出")
    return chosen


def get_namespaces(kubeconfig: str, context: str) -> List[str]:
    result = run_kubectl(
        kubeconfig,
        ["--context", context, "get", "namespaces", "-o", "json"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise KcommError(
            "无法获取命名空间列表（权限或网络）。"
            f" kubectl 输出: {trim_error(result.stderr, 350)}"
        )

    payload = json.loads(result.stdout or "{}")
    items = payload.get("items") or []
    namespaces = [item["metadata"]["name"] for item in items if item.get("metadata")]
    if not namespaces:
        raise KcommError("未找到任何命名空间。")
    return namespaces


def select_namespace(namespaces: Sequence[str]) -> Optional[str]:
    choices = [{"name": ALL_NAMESPACES_LABEL, "value": None}]
    choices.extend({"name": name, "value": name} for name in namespaces)
    return prompt_fuzzy("Namespace (命名空间，输入关键字过滤)> ", choices)


def get_pods(
    kubeconfig: str,
    context: str,
    namespace: Optional[str],
    phase: str,
) -> List[PodInfo]:
    args = ["--context", context, "get", "pods"]
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("-A")
    args.extend(["--field-selector", f"status.phase={phase}", "-o", "json"])

    result = run_kubectl(kubeconfig, args, capture_output=True, check=False)
    if result.returncode != 0:
        raise KcommError(
            "无法访问集群或没有权限。"
            f" kubectl 输出: {trim_error(result.stderr, 450)}"
        )

    pods = parse_pods_from_json(result.stdout)
    if not pods:
        if namespace:
            raise KcommError(f'命名空间 "{namespace}" 下没有 {phase} 状态的 Pod。')
        raise KcommError(f"当前集群没有 {phase} 状态的 Pod。")
    return pods


def parse_pods_from_json(raw_json: str) -> List[PodInfo]:
    payload = json.loads(raw_json or "{}")
    items = payload.get("items") or []
    pods: List[PodInfo] = []
    for item in items:
        metadata = item.get("metadata") or {}
        status = item.get("status") or {}
        pods.append(
            PodInfo(
                namespace=metadata.get("namespace", ""),
                name=metadata.get("name", ""),
                status=status.get("phase", ""),
                start_time=status.get("startTime", ""),
                pod_ip=status.get("podIP", ""),
            )
        )
    return pods


def select_pod(namespace: Optional[str], pods: Sequence[PodInfo]) -> PodInfo:
    choices = []
    for pod in pods:
        choices.append({"name": format_pod_label(namespace, pod), "value": pod})

    chosen = prompt_fuzzy("Pod (输入关键字模糊匹配)> ", choices)
    if chosen is None:
        raise KcommError("未选择 Pod，已退出")
    return chosen


def format_pod_label(selected_namespace: Optional[str], pod: PodInfo) -> str:
    prefix = "" if selected_namespace else f"{pod.namespace} | "
    display_start_time = format_kubernetes_timestamp(pod.start_time)
    return (
        f"{prefix}{pod.name} | {pod.status or '-'} | "
        f"{display_start_time} | {pod.pod_ip or '-'}"
    )


def format_kubernetes_timestamp(
    raw_timestamp: str, target_tz: Optional[tzinfo] = None
) -> str:
    if not raw_timestamp:
        return "-"

    try:
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return raw_timestamp

    local_timestamp = timestamp.astimezone(target_tz)
    return local_timestamp.strftime("%Y-%m-%d %H:%M:%S %z")


def get_containers(
    kubeconfig: str,
    context: str,
    namespace: str,
    pod: str,
) -> List[str]:
    result = run_kubectl(
        kubeconfig,
        ["--context", context, "get", "pod", "-n", namespace, pod, "-o", "json"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise KcommError(
            "无法获取容器列表。"
            f" kubectl 输出: {trim_error(result.stderr, 250)}"
        )

    payload = json.loads(result.stdout or "{}")
    containers = payload.get("spec", {}).get("containers") or []
    names = [item.get("name", "") for item in containers if item.get("name")]
    if not names:
        raise KcommError("未获取到容器名称。")
    return names


def select_container(containers: Sequence[str]) -> Optional[str]:
    if len(containers) <= 1:
        return containers[0]

    choices = [{"name": name, "value": name} for name in containers]
    chosen = prompt_select("容器> ", choices, allow_skip=True)
    if chosen is None:
        return containers[0]
    return str(chosen)


def exec_into_pod(
    kubeconfig: str,
    context: str,
    namespace: str,
    pod: str,
    container: Optional[str],
) -> int:
    shell_name = detect_shell(kubeconfig, context, namespace, pod, container)
    args = ["kubectl", "--context", context, "exec", "-it", "-n", namespace, pod]
    if container:
        args.extend(["-c", container])
    args.extend(["--", shell_name])

    env = kubectl_env(kubeconfig)
    return run_interactive_kubectl(args, env)


def detect_shell(
    kubeconfig: str,
    context: str,
    namespace: str,
    pod: str,
    container: Optional[str],
) -> str:
    args = ["kubectl", "--context", context, "exec", "-n", namespace, pod]
    if container:
        args.extend(["-c", container])
    args.extend(["--", "test", "-x", "/bin/bash"])

    result = subprocess.run(
        args,
        env=kubectl_env(kubeconfig),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        return "/bin/bash"
    return "/bin/sh"


def kubectl_env(kubeconfig: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["KUBECONFIG"] = kubeconfig
    return env


def run_kubectl(
    kubeconfig: str,
    args: Sequence[str],
    capture_output: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = ["kubectl", *args]
    return subprocess.run(
        command,
        env=kubectl_env(kubeconfig),
        capture_output=capture_output,
        text=True,
        check=check,
    )


def run_interactive_kubectl(args: Sequence[str], env: Mapping[str, str]) -> int:
    process = subprocess.Popen(
        list(args),
        env=dict(env),
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr_thread: Optional[threading.Thread] = None
    if process.stderr is not None:
        stderr_thread = threading.Thread(
            target=forward_filtered_stderr,
            args=(process.stderr,),
            daemon=True,
        )
        stderr_thread.start()

    return_code = process.wait()
    if stderr_thread is not None:
        stderr_thread.join()
    if process.stderr is not None:
        process.stderr.close()
    return return_code


def forward_filtered_stderr(stderr_stream: Any) -> None:
    for line in stderr_stream:
        if should_filter_kubectl_stderr_line(line):
            continue
        sys.stderr.write(line)
        sys.stderr.flush()


def should_filter_kubectl_stderr_line(line: str) -> bool:
    return bool(FILTERED_KUBECTL_STDERR_PATTERN.search(line))


def trim_error(raw: Optional[str], limit: int) -> str:
    text = (raw or "").strip()
    if not text:
        return "无详细输出"
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def prompt_select(
    message: str,
    choices: Sequence[Dict[str, Any]],
    allow_skip: bool = False,
) -> Any:
    inquirer = load_inquirer()
    return inquirer.select(
        message=message,
        choices=list(choices),
        pointer=">",
        mandatory=not allow_skip,
        raise_keyboard_interrupt=not allow_skip,
    ).execute()


def prompt_fuzzy(message: str, choices: Sequence[Dict[str, Any]]) -> Any:
    inquirer = load_inquirer()
    return inquirer.fuzzy(
        message=message,
        choices=list(choices),
        default="",
        pointer=">",
        match_exact=True,
        raise_keyboard_interrupt=True,
    ).execute()


def load_inquirer() -> Any:
    try:
        from InquirerPy import inquirer
    except ImportError as exc:
        raise KcommError(
            "未安装 InquirerPy，请先执行 `python3 -m pip install InquirerPy` "
            "或按 pyproject.toml 安装依赖。"
        ) from exc
    return inquirer


if __name__ == "__main__":
    raise SystemExit(main())
