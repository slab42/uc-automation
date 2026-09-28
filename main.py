#!/usr/bin/env python3

"""
UC Automation menu launcher.

Interactive entry point that lists scripts under cucm/, cuc/, cube/, and
webex/ (only those with a "# TITLE:" comment) and runs the chosen one as
a real subprocess - see setup/menu.py for why it's never imported.

Usage:
    python3 main.py                 Launch the interactive menu.
    python3 main.py --list          Print "path<TAB>title<TAB>flags" for
                                     every discovered script and exit.
                                     No ANSI escapes - safe to pipe.
    python3 main.py --list --verbose
                                     Also print skipped files (with the
                                     reason) and duplicate-title warnings.
    python3 main.py --no-clear      Never clear the screen between menus.

Environment:
    UC_LAUNCHER_NO_CLEAR=1          Same effect as --no-clear.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from setup.launcher_config import LauncherConfig
from setup.script_registry import discover
from setup import menu


def _print_list(root: Path, verbose: bool) -> int:
    entries, skipped = discover(root)
    cfg = LauncherConfig(root)

    for e in entries:
        flags = []
        if e.takes_args:
            flags.append('args')
        if cfg.is_favorite(e.rel):
            flags.append('fav')
        if cfg.is_hidden(e.rel):
            flags.append('hidden')
        print(f"{e.rel}\t{e.title}\t{','.join(flags)}")

    if verbose:
        if skipped:
            print("\n# Skipped files:")
            for rel, reason in skipped:
                print(f"{rel}\t{reason}")

        by_cat = {}
        for e in entries:
            by_cat.setdefault(e.category, {}).setdefault(e.title, 0)
            by_cat[e.category][e.title] += 1
        dupes = [
            f"{cat}: duplicate title {title!r} used by {count} scripts"
            for cat, titles in by_cat.items()
            for title, count in titles.items()
            if count > 1
        ]
        if dupes:
            print("\n# Duplicate titles:")
            for line in dupes:
                print(line)

    return 0


def main() -> int:
    argv = sys.argv[1:]
    do_list = '--list' in argv
    verbose = '--verbose' in argv
    no_clear_flag = '--no-clear' in argv

    if do_list:
        return _print_list(ROOT, verbose)

    no_clear = no_clear_flag or os.environ.get('UC_LAUNCHER_NO_CLEAR') == '1'
    return menu.run(ROOT, verbose=verbose, no_clear=no_clear)


if __name__ == '__main__':
    sys.exit(main())
