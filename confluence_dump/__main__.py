"""Lightweight ConfluenceBridge version CLI.

The export and PDF entrypoints intentionally remain independent; this module
does not import them or run any export operation.
"""
from __future__ import annotations

import argparse
import sys

from .version import display_version


class _VersionAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None) -> None:
        parser._print_message(f"confluencebridge {display_version()}\n", sys.stdout)
        parser.exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="confluencebridge",
        description="ConfluenceBridge tool identity; exports remain separate scripts",
    )
    parser.add_argument("--version", action=_VersionAction, nargs=0,
                        help="show exact executing version (offline)")
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version", help="inspect the executing tool version")
    version_commands = version.add_subparsers(dest="version_command", required=True)
    check = version_commands.add_parser(
        "check",
        help="check the installed commit against public GitHub (network, read-only)",
    )
    check.add_argument("--branch", help="override the GitHub comparison branch")
    args = parser.parse_args(argv)
    if args.command == "version" and args.version_command == "check":
        from .version_check import check_remote_version
        result = check_remote_version(branch=args.branch)
        print(result.render(), end="")
        return result.exit_code
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
