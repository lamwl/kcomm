"""kcomm package."""

__version__ = "0.2.0"


def main() -> int:
    from .cli import main as cli_main

    return cli_main()


__all__ = ["__version__", "main"]
