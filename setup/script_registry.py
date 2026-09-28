#!/usr/bin/env python3

"""
Script discovery for the UC Automation menu launcher.

Walks the fixed set of category directories (CUCM/CUC/CUBE/Webex), finds
runnable scripts, and extracts just enough metadata (a short title, an
optional description, whether the script accepts extra CLI args) to build
a menu. This module never runs anything - see setup/menu.py for that.

Only a script with a "# TITLE:" comment in its first 5 lines is eligible
to appear in the menu. Everything else is reported back as "skipped" with
a reason, so a human can fix it (or not) without the launcher guessing.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# (menu label, directory name under repo root, description shown on main menu)
CATEGORIES = [
    ("CUCM", "cucm", "Cisco Unified Communications Manager"),
    ("CUC", "cuc", "Cisco Unity Connection"),
    ("CUBE", "cube", "Cisco Unified Border Element"),
    ("Webex", "webex", "Webex Calling / Control Hub"),
]

# Directories to never recurse into, wherever they occur under a category root.
_SKIP_DIR_PARTS = {"__pycache__", "schema", "examples", ".git", "DEV"}

# Support modules / test scripts that are never menu items, even though
# they live inside a category directory and would otherwise be discovered.
_DENYLIST = {
    "cucm/ucmAPI.py",
    "cucm/general.py",
    "cucm/test_css_schema.py",
    "cucm/find_css_table.py",
    "setup/test_credentials_loader.py",
}

_TITLE_RE = re.compile(r'^\s*#\s*TITLE:\s*(.+?)\s*$')


@dataclass
class ScriptEntry:
    path: Path       # absolute path to the script
    rel: str         # repo-relative POSIX path, e.g. "cucm/move_DN_partition.py"
    category: str    # one of the CATEGORIES labels, e.g. "CUCM"
    title: str       # from the "# TITLE:" comment line
    takes_args: bool  # True if the script uses argparse or sys.argv


def read_title(path: Path) -> Optional[str]:
    """
    Return the script's menu title, or None if it has no "# TITLE:" line.

    Deliberately a plain line scan (no AST) over only the first 5 lines.
    That means a file with a syntax error can still surface a title, and
    nothing deeper in the file can ever leak into a menu label.
    """
    try:
        with path.open(encoding='utf-8', errors='replace') as fh:
            for _, line in zip(range(5), fh):
                m = _TITLE_RE.match(line)
                if m:
                    return ' '.join(m.group(1).split())[:40]
    except OSError:
        return None
    return None


def read_description(path: Path) -> Optional[str]:
    """
    Return the script's descriptive docstring/comment block for the 'i'
    (details) view, or None if there isn't one. Used only for display -
    never for discovery or filtering.

    ast.get_docstring() returns None for scripts that put a statement
    (commonly "import warnings") before their description block, so this
    falls back to the first bare string expression anywhere in the module
    body.
    """
    try:
        src = path.read_text(encoding='utf-8', errors='replace')
        tree = ast.parse(src)
    except (SyntaxError, ValueError, UnicodeDecodeError, OSError):
        return None

    text = ast.get_docstring(tree)
    if not text:
        for node in tree.body:
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                text = node.value.value
                break
    return text


def _takes_args(tree: ast.AST) -> bool:
    """True if the module builds an argparse.ArgumentParser or indexes sys.argv."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if name == 'ArgumentParser':
                return True
        if isinstance(node, ast.Subscript):
            val = node.value
            if isinstance(val, ast.Attribute) and val.attr == 'argv':
                return True
            if isinstance(val, ast.Name) and val.id == 'argv':
                return True
    return False


def _eligible_name(name: str) -> bool:
    if name == '__init__.py':
        return False
    if name.startswith(('_', '.', 'test_')):
        return False
    return True


def _iter_py_files(cat_root: Path):
    for path in sorted(cat_root.rglob('*.py')):
        rel_parts = path.relative_to(cat_root).parts
        if any(part in _SKIP_DIR_PARTS for part in rel_parts):
            continue
        yield path


def discover(root: Path) -> Tuple[List[ScriptEntry], List[Tuple[str, str]]]:
    """
    Walk every category directory under root and classify each .py file.

    Returns (entries, skipped):
      entries - ScriptEntry list, ready for the menu
      skipped - [(rel_path, reason), ...] for files that were parseable
                 Python but did not qualify (empty file, parse error, or
                 missing "# TITLE:" line). Name-rule and denylist skips
                 are not reported - they're not worth a human's attention.
    """
    entries: List[ScriptEntry] = []
    skipped: List[Tuple[str, str]] = []
    category_order = {label: i for i, (label, _, _) in enumerate(CATEGORIES)}

    for label, dirname, _desc in CATEGORIES:
        cat_root = root / dirname
        if not cat_root.is_dir():
            continue

        for path in _iter_py_files(cat_root):
            if not _eligible_name(path.name):
                continue

            rel = path.relative_to(root).as_posix()
            if rel in _DENYLIST:
                continue

            try:
                src = path.read_text(encoding='utf-8', errors='replace')
            except OSError as e:
                skipped.append((rel, f"does not parse: {type(e).__name__}"))
                continue

            if not src.strip():
                skipped.append((rel, "empty file"))
                continue

            try:
                tree = ast.parse(src)
            except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as e:
                skipped.append((rel, f"does not parse: {type(e).__name__}"))
                continue

            title = read_title(path)
            if title is None:
                skipped.append((rel, "no # TITLE: line"))
                continue

            entries.append(ScriptEntry(
                path=path,
                rel=rel,
                category=label,
                title=title,
                takes_args=_takes_args(tree),
            ))

    entries.sort(key=lambda e: (category_order.get(e.category, 99), e.title.lower()))
    return entries, skipped
