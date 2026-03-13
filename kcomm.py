#!/usr/bin/env python3
"""兼容入口，转发到 `src/kcomm/cli.py`。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main() -> int:
    cli_module = importlib.import_module("kcomm.cli")
    return cli_module.main()


if __name__ == "__main__":
    raise SystemExit(main())
