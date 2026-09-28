#!/usr/bin/env python3

"""
Interactive menu screens for the UC Automation launcher.

Two levels deep only: main menu -> category (or Favorites) menu. Selecting
a numbered item runs that script immediately - the scripts already have
their own confirmation prompts, so the launcher doesn't add a second one.

--------------------------------------------------------------------------
IMPORTANT: scripts are launched as a separate child process (see
subprocess.run below). Never use runpy.run_path() here, never use a
plain "import" of the target script, and never use exec() on its source.
Do not "optimize" this to an in-process call. Reasons, all verified
against the scripts in this repo:

  1. 26 scripts under cucm/ do a bare sibling import ("from ucmAPI import
     AXL") that only resolves when the script's own directory is
     sys.path[0] - i.e. when it's run as "python3 <name>.py" from inside
     cucm/. Importing it as a module breaks that.
  2. Scripts resolve relative paths (e.g. "../_logs/...",
     basepath.parent / "_DATA" / "clusters.csv") against their own
     current working directory and must run with cwd set to their own
     directory.
  3. sys.exit() appears in 37 files / 83 call sites across cucm/, cuc/,
     cube/ and webex/ (verified 2026-09-24). In-process, each one becomes
     an uncaught SystemExit that would kill the launcher.
  4. setup/logger.py uses a single module-global logger and APPENDS a
     handler on every call - running two scripts in one process would
     duplicate every log line.
  5. setup/var_loader.py derives its .var filename from sys.argv[0]. In-
     process that would resolve to ".var/main.py.var" instead of the
     target script's own .var file.
  6. All 14 top-level webex/*.py scripts have no "if __name__" guard -
     their body runs at import time, with no chance to control it.

A real child process sidesteps every one of these. Keep it that way.
--------------------------------------------------------------------------
"""

import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from setup.launcher_config import LauncherConfig
from setup.prompt_utils import prompt_yes_no
from setup.script_registry import CATEGORIES, ScriptEntry, discover, read_description

ITEMS_PER_PAGE = 9

_CLEAR = "\033[H\033[2J"

_TWO_STEP_RE = re.compile(r'^([ifxa])([1-9])$')

_ITEM_PROMPT_VERB = {
    'i': 'Show details for',
    'f': 'Toggle favorite for',
    'x': 'Toggle hidden for',
    'a': 'Run with args for',
}


class _Redraw(Exception):
    """Raised when Ctrl-C interrupts an input() - caller should redraw."""


class _QuitNow(Exception):
    """Raised when Ctrl-D (EOF) is hit - caller should exit cleanly."""


def _input(prompt: str) -> str:
    """input() wrapper: Ctrl-C redraws the current menu, Ctrl-D quits."""
    try:
        return input(prompt)
    except KeyboardInterrupt:
        raise _Redraw()
    except EOFError:
        raise _QuitNow()


@dataclass
class _State:
    entries: List[ScriptEntry] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)


def _paginate(items: list, page: int):
    total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = min(max(page, 0), total_pages - 1)
    start = page * ITEMS_PER_PAGE
    return items[start:start + ITEMS_PER_PAGE], total_pages, page


def _clear(effective_clear: bool):
    if effective_clear:
        print(_CLEAR, end="")


def _visible(cfg: LauncherConfig, cat_entries: List[ScriptEntry]) -> List[ScriptEntry]:
    if cfg.show_hidden:
        return cat_entries
    return [e for e in cat_entries if not cfg.is_hidden(e.rel)]


def _confirm_quit() -> bool:
    try:
        return prompt_yes_no("Quit the launcher?")
    except _Redraw:
        return False


def run(root: Path, verbose: bool = False, no_clear: bool = False) -> int:
    """Entry point called by main.py. Runs until the user quits."""
    cfg = LauncherConfig(root)
    effective_clear = cfg.clear_screen and sys.stdout.isatty() and not no_clear
    entries, skipped = discover(root)
    state = _State(entries=entries, skipped=skipped)

    try:
        _main_menu(root, cfg, state, effective_clear)
    except _QuitNow:
        print()
    return 0


# -- main menu -------------------------------------------------------------

def _main_menu(root: Path, cfg: LauncherConfig, state: _State, effective_clear: bool):
    while True:
        by_cat = {label: [] for label, _, _ in CATEGORIES}
        for e in state.entries:
            by_cat.setdefault(e.category, []).append(e)
        existing_rels = {e.rel for e in state.entries}
        fav_count = len([r for r in cfg.favorites if r in existing_rels])

        rows = [("FAV", "Favorites", "")] + [
            (label, label, desc) for label, _dirname, desc in CATEGORIES
        ]
        counts = [fav_count] + [
            len(_visible(cfg, by_cat.get(label, []))) for label, _d, _desc in CATEGORIES
        ]

        _clear(effective_clear)
        print("=" * 80)
        print(" UC Automation Launcher")
        print("=" * 80)
        print()
        for i, ((kind, label, desc), count) in enumerate(zip(rows, counts), 1):
            if kind == "FAV":
                print(f"  {i}. {'Favorites':<55}({count})")
            else:
                print(f"  {i}. {label:<10}{desc:<40}({count})")
        print()

        no_title = [s for s in state.skipped if s[1] == "no # TITLE: line"]
        if no_title:
            print(f"  ! {len(no_title)} scripts have no \"# TITLE:\" line and are hidden.")
            print(f"    Run: python3 main.py --list --verbose")
            print()

        print("  ? - help      r - rescan      0 / q - quit")
        print()

        try:
            choice = _input(f"Select [1-{len(rows)}] or command: ").strip().lower()
        except _Redraw:
            continue

        if choice == '':
            continue
        if choice in ('0', 'q'):
            if choice == 'q' and not _confirm_quit():
                continue
            raise _QuitNow()
        if choice == '?':
            _show_help(scope='main')
            continue
        if choice == 'r':
            state.entries, state.skipped = discover(root)
            print("\nRescanned.")
            continue
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(rows):
                kind = rows[idx][0]
                if kind == "FAV":
                    _favorites_menu(root, cfg, state, effective_clear)
                else:
                    _category_menu(root, cfg, state, kind, effective_clear)
            else:
                print("Invalid selection.")
            continue

        print("Unknown command. Press ? for help.")


# -- category menu ----------------------------------------------------

def _category_row(e: ScriptEntry, cfg: LauncherConfig, show_hidden: bool) -> str:
    fav_mark = '*' if cfg.is_favorite(e.rel) else ' '
    tag = '[args]' if e.takes_args else '-'
    hid = ' (hidden)' if show_hidden and cfg.is_hidden(e.rel) else ''
    return f"{fav_mark} {e.title:<40}{tag}{hid}"


def _category_menu(root: Path, cfg: LauncherConfig, state: _State, label: str,
                    effective_clear: bool):
    page = 0
    while True:
        cat_entries = [e for e in state.entries if e.category == label]
        visible = _visible(cfg, cat_entries)
        hidden_count = len([e for e in cat_entries if cfg.is_hidden(e.rel)])
        page_items, total_pages, page = _paginate(visible, page)

        _clear(effective_clear)
        print("=" * 80)
        header = f" {label}  -  {len(visible)} scripts"
        if total_pages > 1:
            pad = max(1, 68 - len(header))
            header += " " * pad + f"Page {page + 1}/{total_pages}"
        print(header)
        print("=" * 80)
        print()

        if not cat_entries:
            print("  (no scripts in this category)")
        elif not visible:
            print(f"  (all {len(cat_entries)} scripts in this category are hidden)")
        else:
            for i, e in enumerate(page_items, 1):
                print(f"  {i}. {_category_row(e, cfg, cfg.show_hidden)}")

        print()
        if visible:
            note = "  * = favorite"
            if hidden_count and not cfg.show_hidden:
                note += f"            {hidden_count} hidden (press s to show)"
            elif hidden_count and cfg.show_hidden:
                note += f"            {hidden_count} hidden (shown, press s to re-hide)"
            print(note)
            print()

        if not visible:
            print("  s - show hidden      0 - main menu      q - quit      ? - help")
        elif total_pages > 1:
            print("  n - next page    i - details     f - favorite     a - run with args")
            print("  p - prev page    x - hide        s - show hidden  r - rescan")
            print("  0 - main menu    q - quit        ? - help")
        else:
            print("  i - details      f - favorite     a - run with args   x - hide")
            print("  s - show hidden  r - rescan       0 - main menu       q - quit")
            print("  ? - help")
        print()

        prompt = f"Select [1-{len(page_items)}] or command: " if page_items else "Command: "
        try:
            choice = _input(prompt).strip().lower()
        except _Redraw:
            continue

        if choice == '':
            continue
        if choice == '0':
            return
        if choice == 'q':
            if _confirm_quit():
                raise _QuitNow()
            continue
        if choice == '?':
            _show_help(scope='category')
            continue
        if choice == 'r':
            state.entries, state.skipped = discover(root)
            print("\nRescanned.")
            continue
        if choice == 's':
            cfg.toggle_show_hidden()
            page = 0
            continue
        if choice == 'n':
            if page < total_pages - 1:
                page += 1
            else:
                print("Already on the last page.")
            continue
        if choice == 'p':
            if page > 0:
                page -= 1
            continue

        cmd, target = _parse_two_step(choice, page_items)
        if target is not None:
            _dispatch_item_command(cmd, target, cfg, effective_clear)
            continue

        if choice in ('i', 'f', 'x', 'a'):
            _prompt_and_dispatch(choice, page_items, cfg, effective_clear)
            continue

        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(page_items):
                _run_and_report(page_items[n - 1])
            else:
                print("Invalid selection.")
            continue

        print("Unknown command. Press ? for help.")


# -- favorites menu -----------------------------------------------

def _missing_favorites_line(n: int) -> str:
    if n == 1:
        return ('(1 favorite points to a script that no longer exists; '
                 'press c to clear it)')
    return (f'({n} favorites point to scripts that no longer exist; '
            f'press c to clear them)')


def _untitled_favorites_line(n: int) -> str:
    if n == 1:
        return ('(1 favorite has no "# TITLE:" line and is hidden; '
                 'add the line to restore it)')
    return (f'({n} favorites have no "# TITLE:" lines and are hidden; '
            f'add the lines to restore them)')


def _favorites_menu(root: Path, cfg: LauncherConfig, state: _State, effective_clear: bool):
    page = 0
    while True:
        by_rel = {e.rel: e for e in state.entries}
        fav_entries = [by_rel[r] for r in cfg.favorites if r in by_rel]
        # A favorite not in the registry is in one of two different states:
        #   - untitled: the file is still on disk, it just lacks (or lost)
        #     its "# TITLE:" line, so discover() skipped it. Not stale -
        #     one edit restores it. Must never be cleared by 'c'.
        #   - missing: the file is genuinely gone (renamed/deleted).
        #     This is the only case 'c' may remove.
        untitled_favs = [r for r in cfg.favorites
                         if r not in by_rel and (root / r).exists()]
        missing_favs = [r for r in cfg.favorites
                        if r not in by_rel and not (root / r).exists()]
        page_items, total_pages, page = _paginate(fav_entries, page)

        _clear(effective_clear)
        print("=" * 80)
        header = f" Favorites  -  {len(fav_entries)} scripts"
        if total_pages > 1:
            pad = max(1, 68 - len(header))
            header += " " * pad + f"Page {page + 1}/{total_pages}"
        print(header)
        print("=" * 80)
        print()

        if not fav_entries:
            print("  No favorites yet. Press f in a category menu to add one.")
        else:
            for i, e in enumerate(page_items, 1):
                tag = '[args]' if e.takes_args else '-'
                print(f"  {i}. {e.category.lower():<8} {e.title:<40}{tag}")

        print()
        if missing_favs:
            print(f"  {_missing_favorites_line(len(missing_favs))}")
        if untitled_favs:
            print(f"  {_untitled_favorites_line(len(untitled_favs))}")
        if missing_favs or untitled_favs:
            print()

        if total_pages > 1:
            print("  n - next page    i - details     f - favorite     a - run with args")
            print("  p - prev page    0 - main menu    q - quit         ? - help")
        else:
            print("  i - details      f - favorite     a - run with args")
            print("  0 - main menu    q - quit         ? - help")
        print()

        prompt = f"Select [1-{len(page_items)}] or command: " if page_items else "Command: "
        try:
            choice = _input(prompt).strip().lower()
        except _Redraw:
            continue

        if choice == '':
            continue
        if choice == '0':
            return
        if choice == 'q':
            if _confirm_quit():
                raise _QuitNow()
            continue
        if choice == '?':
            _show_help(scope='favorites')
            continue
        if choice == 'r':
            state.entries, state.skipped = discover(root)
            print("\nRescanned.")
            continue
        if choice == 'n':
            if page < total_pages - 1:
                page += 1
            else:
                print("Already on the last page.")
            continue
        if choice == 'p':
            if page > 0:
                page -= 1
            continue
        if choice == 'c' and missing_favs:
            if prompt_yes_no(f"Remove {len(missing_favs)} stale favorite(s)?"):
                cfg.remove_stale_favorites(set(missing_favs))
            continue

        cmd, target = _parse_two_step(choice, page_items)
        if target is not None:
            _dispatch_item_command(cmd, target, cfg, effective_clear)
            continue

        if choice in ('i', 'f', 'a'):
            _prompt_and_dispatch(choice, page_items, cfg, effective_clear)
            continue

        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(page_items):
                _run_and_report(page_items[n - 1])
            else:
                print("Invalid selection.")
            continue

        print("Unknown command. Press ? for help.")


# -- shared item commands (i / f / x / a) -----------------------------

def _parse_two_step(choice: str, page_items: list) -> Tuple[Optional[str], Optional[ScriptEntry]]:
    """Handle shorthand like 'f3' -> ('f', page_items[2]) in one keystroke pair."""
    m = _TWO_STEP_RE.fullmatch(choice)
    if not m:
        return None, None
    cmd, num = m.group(1), int(m.group(2))
    if 1 <= num <= len(page_items):
        return cmd, page_items[num - 1]
    return None, None


def _prompt_and_dispatch(cmd: str, page_items: list, cfg: LauncherConfig, effective_clear: bool):
    verb = _ITEM_PROMPT_VERB[cmd]
    try:
        sel = _input(f"{verb} which item? (1-{len(page_items)}, Enter to cancel): ").strip()
    except _Redraw:
        return
    if not sel:
        return
    if sel.isdigit() and 1 <= int(sel) <= len(page_items):
        _dispatch_item_command(cmd, page_items[int(sel) - 1], cfg, effective_clear)
    else:
        print("Invalid selection.")


def _dispatch_item_command(cmd: str, entry: ScriptEntry, cfg: LauncherConfig,
                            effective_clear: bool):
    if cmd == 'i':
        _show_details(entry, effective_clear)
    elif cmd == 'f':
        is_fav = cfg.toggle_favorite(entry.rel)
        print(f"\n{'Added to' if is_fav else 'Removed from'} favorites: {entry.title}")
    elif cmd == 'x':
        is_hidden = cfg.toggle_hidden(entry.rel)
        print(f"\n{'Hidden' if is_hidden else 'Unhidden'}: {entry.title}")
    elif cmd == 'a':
        _run_with_args(entry)


def _show_details(entry: ScriptEntry, effective_clear: bool):
    _clear(effective_clear)
    print("=" * 80)
    print(f" {entry.title}")
    print("=" * 80)
    print()
    print(f"  Path: {entry.rel}")
    if entry.takes_args:
        print("  Accepts extra arguments: [args]")
    print()
    desc = read_description(entry.path)
    print(desc if desc else "No description available.")
    print()
    try:
        input("Press Enter to return to the menu... ")
    except (KeyboardInterrupt, EOFError):
        pass


def _run_with_args(entry: ScriptEntry):
    try:
        raw = _input("Extra arguments: ").strip()
    except _Redraw:
        return
    try:
        extra = shlex.split(raw) if raw else []
    except ValueError as e:
        print(f"Could not parse arguments: {e}")
        return
    _run_and_report(entry, extra)


# -- running a script ---------------------------------------------------

def _run_and_report(entry: ScriptEntry, extra_args: Optional[List[str]] = None):
    print()
    print("-" * 80)
    print(f" Running: {entry.title}  ({entry.rel})")
    print("-" * 80)
    print()

    # Always a real subprocess - see the module docstring for why. Bare
    # filename (not an absolute path) so sys.argv[0] matches what a user
    # would type by hand, cwd set to the script's own directory (never
    # Path.cwd() - that's the launcher's directory, not the script's) so
    # its sibling imports and relative paths resolve, and stdio is left
    # fully inherited - do not pass capture_output=, stdout=, or stderr=
    # - so input()/getpass() keep working. Never pass shell=True (no
    # shell interpretation) and never pass start_new_session=True (do
    # not detach the child into a new session/process group) - a hung
    # child must stay killable with Ctrl-C alongside the launcher.
    cmd = [sys.executable, entry.path.name, *(extra_args or [])]
    try:
        proc = subprocess.run(cmd, cwd=str(entry.path.parent), check=False)
        rc = proc.returncode
    except KeyboardInterrupt:
        # The child shares our process group, so Ctrl-C hits it too.
        # Treat it as an interrupted run and keep the launcher alive.
        rc = 130

    print()
    if rc == 0:
        print("Completed.")
    elif rc == 130:
        print("Interrupted by user (Ctrl-C).")
    elif rc < 0:
        print(f"Terminated by signal {-rc}.")
    else:
        print(f"Exited with code {rc}.")

    try:
        input("\nPress Enter to return to the menu... ")
    except (KeyboardInterrupt, EOFError):
        pass


# -- help -------------------------------------------------------------

def _show_help(scope: str):
    print()
    print("=" * 80)
    print(" Help")
    print("=" * 80)
    print()
    if scope == 'main':
        print("  Pick a number to open that menu.")
        print("  r      - rescan the repo for scripts")
        print("  0 / q  - quit the launcher (q asks for confirmation)")
    else:
        print("  Pick a number to run that script immediately - scripts have")
        print("  their own confirmation prompts, so there is no second one here.")
        print()
        print("  n / p  - next / previous page")
        print("  i      - show the script's full description without running it")
        print("  f      - toggle favorite")
        if scope == 'category':
            print("  x      - toggle hidden (exclude from the normal list)")
            print("  s      - toggle showing hidden scripts")
        print("  a      - run the script with extra command-line arguments")
        print("  r      - rescan the repo for scripts")
        print("  0      - back to the main menu")
        print("  q      - quit the launcher")
        print()
        print("  Shorthand: a letter immediately followed by a digit, e.g. f3,")
        print("  applies that command to item 3 without a second prompt.")
    print()
    try:
        input("Press Enter to continue... ")
    except (KeyboardInterrupt, EOFError):
        pass
