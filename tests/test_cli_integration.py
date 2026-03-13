import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import kcomm.cli as cli
from kcomm import __version__
from kcomm.cli import ContextInfo, PodInfo


def write_mock_kubectl(bin_dir: Path) -> Path:
    script = bin_dir / "kubectl"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys

            args = sys.argv[1:]
            log_path = os.environ.get("KCOMM_KUBECTL_LOG")

            if log_path:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "args": args,
                        "kubeconfig": os.environ.get("KUBECONFIG"),
                    }) + "\\n")

            def emit(payload):
                sys.stdout.write(json.dumps(payload))

            def split_context(argv):
                if len(argv) >= 2 and argv[0] == "--context":
                    return argv[1], argv[2:]
                return None, argv

            context, rest = split_context(args)

            if rest == ["config", "view", "-o", "json"]:
                emit({
                    "contexts": [
                        {
                            "name": "prod",
                            "context": {
                                "cluster": "cluster-a",
                                "user": "alice",
                                "namespace": "default",
                            },
                        }
                    ]
                })
                raise SystemExit(0)

            if rest == ["get", "namespaces", "-o", "json"]:
                emit({
                    "items": [
                        {"metadata": {"name": "default"}},
                        {"metadata": {"name": "ops"}},
                    ]
                })
                raise SystemExit(0)

            if len(rest) >= 2 and rest[:2] == ["get", "pods"]:
                namespace = None
                all_namespaces = "-A" in rest
                if "-n" in rest:
                    namespace = rest[rest.index("-n") + 1]

                items = [
                    {
                        "metadata": {"namespace": "default", "name": "api-123"},
                        "status": {
                            "phase": "Running",
                            "startTime": "2026-03-13T10:00:00Z",
                            "podIP": "10.0.0.5",
                        },
                    },
                    {
                        "metadata": {"namespace": "ops", "name": "worker-456"},
                        "status": {
                            "phase": "Running",
                            "startTime": "2026-03-13T11:00:00Z",
                            "podIP": "10.0.0.6",
                        },
                    },
                ]

                if namespace:
                    items = [item for item in items if item["metadata"]["namespace"] == namespace]
                elif not all_namespaces:
                    items = []

                emit({"items": items})
                raise SystemExit(0)

            if len(rest) >= 6 and rest[:2] == ["get", "pod"]:
                namespace = rest[rest.index("-n") + 1]
                pod_name = rest[rest.index("-n") + 2]
                emit({
                    "spec": {
                        "containers": [
                            {"name": f"{namespace}-{pod_name}-main"}
                        ]
                    }
                })
                raise SystemExit(0)

            if rest and rest[0] == "exec":
                if rest[-3:] == ["test", "-x", "/bin/bash"]:
                    raise SystemExit(0 if os.environ.get("MOCK_HAS_BASH") == "1" else 1)
                if rest[-1] in {"/bin/bash", "/bin/sh"}:
                    raise SystemExit(0)

            sys.stderr.write(f"Unhandled kubectl args: {args}\\n")
            raise SystemExit(1)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


class CliWrapperTest(unittest.TestCase):
    def test_wrapper_exposes_version(self) -> None:
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "kcomm"), "--version"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"kcomm {__version__}", result.stdout)


class MockKubectlIntegrationTest(unittest.TestCase):
    def run_main_with_fake_kubectl(
        self,
        *,
        namespace_choice,
        selected_pod: PodInfo,
        has_bash: bool,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            home = temp_root / "home"
            kube_dir = home / ".kube"
            kube_dir.mkdir(parents=True)
            kubeconfig = kube_dir / "config"
            kubeconfig.write_text("kind: Config\n", encoding="utf-8")

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            write_mock_kubectl(bin_dir)

            log_path = temp_root / "kubectl.log"
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "KCOMM_KUBECTL_LOG": str(log_path),
                "MOCK_HAS_BASH": "1" if has_bash else "0",
            }

            prompt_values = [
                ContextInfo(
                    name="prod",
                    cluster="cluster-a",
                    user="alice",
                    namespace="default",
                ),
            ]

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("kcomm.cli.prompt_select", side_effect=prompt_values):
                    with mock.patch(
                        "kcomm.cli.prompt_fuzzy",
                        side_effect=[namespace_choice, selected_pod],
                    ):
                        exit_code = cli.main([])

            records = []
            if log_path.exists():
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    records.append(json.loads(line))
            return exit_code, records, str(kubeconfig)

    def test_main_uses_default_namespace_and_bash(self) -> None:
        exit_code, records, kubeconfig = self.run_main_with_fake_kubectl(
            namespace_choice="default",
            selected_pod=PodInfo(
                namespace="default",
                name="api-123",
                status="Running",
                start_time="2026-03-13T10:00:00Z",
                pod_ip="10.0.0.5",
            ),
            has_bash=True,
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(
            any(record["args"][-1] == "/bin/bash" for record in records),
            records,
        )
        self.assertTrue(
            any(record["kubeconfig"] == kubeconfig for record in records),
            records,
        )
        self.assertTrue(
            any(record["args"][:4] == ["--context", "prod", "get", "pods"] for record in records),
            records,
        )
        self.assertTrue(
            any("-n" in record["args"] and "default" in record["args"] for record in records),
            records,
        )

    def test_main_uses_all_namespaces_and_falls_back_to_sh(self) -> None:
        exit_code, records, _ = self.run_main_with_fake_kubectl(
            namespace_choice=None,
            selected_pod=PodInfo(
                namespace="ops",
                name="worker-456",
                status="Running",
                start_time="2026-03-13T11:00:00Z",
                pod_ip="10.0.0.6",
            ),
            has_bash=False,
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(
            any(record["args"][-1] == "/bin/sh" for record in records),
            records,
        )
        self.assertTrue(
            any("-A" in record["args"] for record in records if record["args"][:4] == ["--context", "prod", "get", "pods"]),
            records,
        )


if __name__ == "__main__":
    unittest.main()
