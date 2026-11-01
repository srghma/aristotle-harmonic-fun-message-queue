
import argparse

from ..completions import generate_carapace_spec, install_carapace_spec


def register(
    subparsers: argparse._SubParsersAction,
    root_parser: argparse.ArgumentParser,
) -> None:
    p = subparsers.add_parser(
        "completions",
        help="Generate shell completions",
    )

    actions = p.add_subparsers(
        dest="completion_action",
        required=True,
    )

    carapace = actions.add_parser(
        "carapace",
        help="Print Carapace completion spec",
    )
    carapace.set_defaults(
        func=_print_carapace,
        root_parser=root_parser,
    )

    install = actions.add_parser(
        "install-carapace",
        help="Generate and install Carapace completion spec",
    )
    install.set_defaults(
        func=_install_carapace,
        root_parser=root_parser,
    )


def _print_carapace(args) -> None:
    print(generate_carapace_spec(args.root_parser), end="")


def _install_carapace(args) -> None:
    path = install_carapace_spec(args.root_parser)
    print(f"Installed: {path}")
