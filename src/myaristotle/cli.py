import argparse

from .commands import COMMAND_MODULES
from .commands.common import RichHelpFormatter


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="myaristotle - Aristotle task watcher, puller, and queue runner",
        formatter_class=RichHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for cmd_module in COMMAND_MODULES:
        cmd_module.register(subparsers)

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
