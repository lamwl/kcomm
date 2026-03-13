import json
import sys
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kcomm.cli import (
    ContextInfo,
    PodInfo,
    build_config_list,
    format_kubernetes_timestamp,
    format_pod_label,
    normalize_path,
    parse_contexts_from_config_view,
    parse_pods_from_json,
    should_filter_kubectl_stderr_line,
)


class BuildConfigListTest(unittest.TestCase):
    def test_merges_all_sources_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            kube_dir = home / ".kube"
            kube_dir.mkdir()
            configs_dir = kube_dir / "configs"
            configs_dir.mkdir()

            list_entry = kube_dir / "from-list.yaml"
            list_entry.write_text("kind: Config\n", encoding="utf-8")

            duplicate_entry = configs_dir / "dup.yaml"
            duplicate_entry.write_text("kind: Config\n", encoding="utf-8")

            config_list = kube_dir / "config-list"
            config_list.write_text(
                "\n".join(
                    [
                        "# comment",
                        "",
                        str(list_entry),
                        str(duplicate_entry),
                    ]
                ),
                encoding="utf-8",
            )

            default_config = kube_dir / "config"
            default_config.write_text("kind: Config\n", encoding="utf-8")

            env = {}
            result = build_config_list(env=env, home=home)

            self.assertEqual(
                result,
                sorted(
                    {
                        normalize_path(str(list_entry)),
                        normalize_path(str(duplicate_entry)),
                        normalize_path(str(default_config)),
                    }
                ),
            )


class ParseFunctionsTest(unittest.TestCase):
    def test_parse_contexts_from_config_view(self) -> None:
        raw = json.dumps(
            {
                "contexts": [
                    {
                        "name": "prod",
                        "context": {
                            "cluster": "cluster-a",
                            "user": "alice",
                            "namespace": "payments",
                        },
                    },
                    {
                        "name": "test",
                        "context": {
                            "cluster": "cluster-b",
                            "user": "bob",
                        },
                    },
                ]
            }
        )

        contexts = parse_contexts_from_config_view(raw)

        self.assertEqual(
            contexts,
            [
                ContextInfo(
                    name="prod",
                    cluster="cluster-a",
                    user="alice",
                    namespace="payments",
                ),
                ContextInfo(
                    name="test",
                    cluster="cluster-b",
                    user="bob",
                    namespace="",
                ),
            ],
        )

    def test_parse_pods_from_json_and_format_label(self) -> None:
        raw = json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "namespace": "default",
                            "name": "api-123",
                        },
                        "status": {
                            "phase": "Running",
                            "startTime": "2026-03-13T10:00:00Z",
                            "podIP": "10.0.0.5",
                        },
                    }
                ]
            }
        )

        pods = parse_pods_from_json(raw)

        self.assertEqual(
            pods,
            [
                PodInfo(
                    namespace="default",
                    name="api-123",
                    status="Running",
                    start_time="2026-03-13T10:00:00Z",
                    pod_ip="10.0.0.5",
                )
            ],
        )
        self.assertEqual(
            format_kubernetes_timestamp(
                "2026-03-13T10:00:00Z",
                timezone(timedelta(hours=8)),
            ),
            "2026-03-13 18:00:00 +0800",
        )
        self.assertEqual(
            format_pod_label(None, pods[0]),
            "default | api-123 | Running | "
            f"{format_kubernetes_timestamp('2026-03-13T10:00:00Z')} | 10.0.0.5",
        )
        self.assertEqual(
            format_pod_label("default", pods[0]),
            "api-123 | Running | "
            f"{format_kubernetes_timestamp('2026-03-13T10:00:00Z')} | 10.0.0.5",
        )

    def test_filter_kubectl_stderr_line(self) -> None:
        self.assertTrue(
            should_filter_kubectl_stderr_line(
                'E0313 15:58:53.286955   53577 memcache.go:287] "Unhandled Error" '
                'err="couldn\'t get resource list for custom.metrics.k8s.io/v1beta1: '
                'the server is currently unable to handle the request"'
            )
        )
        self.assertFalse(
            should_filter_kubectl_stderr_line(
                "Error from server (Forbidden): pods is forbidden"
            )
        )


if __name__ == "__main__":
    unittest.main()
