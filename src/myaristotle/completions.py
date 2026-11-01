
import argparse
from pathlib import Path
from typing import Any

import yaml


SPEC_NAME = "myaristotle"
CARAPACE_CONFIG_DIR = Path(".config/carapace/specs")


def _takes_value(action: argparse.Action) -> bool:
    """Whether an option expects a value."""
    return action.nargs != 0


def _positional_completion(action: argparse.Action) -> list[str]:
    if action.choices:
        return [str(choice) for choice in action.choices]

    if action.type is Path:
        return ["$directories"]

    return []


def _get_subcommands(
    action: argparse._SubParsersAction,
) -> list[dict[str, Any]]:
    commands = []
    seen: set[int] = set()

    for name, child in action.choices.items():
        if id(child) in seen:
            continue

        seen.add(id(child))

        # argparse registers canonical names before their aliases.
        canonical_name = next(
            candidate
            for candidate, parser in action.choices.items()
            if parser is child
        )

        aliases = [
            alias
            for alias, parser in action.choices.items()
            if parser is child and alias != canonical_name
        ]

        description = next(
            (
                choice.help
                for choice in action._choices_actions
                if choice.dest == canonical_name
            ),
            None,
        )

        commands.append(
            parser_to_spec(
                child,
                name=canonical_name,
                aliases=aliases,
                description=description,
            )
        )

    return commands


def parser_to_spec(
    parser: argparse.ArgumentParser,
    *,
    name: str | None = None,
    aliases: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Convert an argparse parser into a Carapace command spec."""

    spec: dict[str, Any] = {
        "name": name or parser.prog.split()[-1],
    }

    if aliases:
        spec["aliases"] = aliases

    description = description or parser.description

    if description:
        spec["description"] = description

    flags: dict[str, str] = {}
    flag_completions: dict[str, list[str]] = {}
    positional_completions: list[list[str]] = []
    commands: list[dict[str, Any]] = []

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            commands.extend(_get_subcommands(action))
            continue

        if isinstance(action, argparse._HelpAction):
            continue

        if action.option_strings:
            suffix = "=" if _takes_value(action) else ""

            # Carapace expects each spelling as a separate flag.
            for option in action.option_strings:
                flags[f"{option}{suffix}"] = ""

                if option.startswith("--") and action.choices:
                    flag_completions[option[2:]] = [
                        str(choice) for choice in action.choices
                    ]

            continue

        positional_completions.append(
            _positional_completion(action)
        )

    if flags:
        spec["flags"] = flags

    completion: dict[str, Any] = {}

    if flag_completions:
        completion["flag"] = flag_completions

    if positional_completions:
        completion["positional"] = positional_completions

    if completion:
        spec["completion"] = completion

    if commands:
        spec["commands"] = commands

    return spec


def generate_carapace_spec(
    parser: argparse.ArgumentParser,
) -> str:
    """Generate a YAML Carapace spec from the CLI parser."""

    spec = parser_to_spec(
        parser,
        name=SPEC_NAME,
        description=parser.description,
    )

    return yaml.safe_dump(
        spec,
        sort_keys=False,
        allow_unicode=True,
    )


def install_carapace_spec(
    parser: argparse.ArgumentParser,
    directory: Path | None = None,
) -> Path:
    """Generate and install the Carapace spec."""

    spec_dir = directory or (
        Path.home() / CARAPACE_CONFIG_DIR
    )

    spec_dir.mkdir(parents=True, exist_ok=True)

    spec_file = spec_dir / f"{SPEC_NAME}.yaml"

    spec_file.write_text(
        generate_carapace_spec(parser),
        encoding="utf-8",
    )

    return spec_file
