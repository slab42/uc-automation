#!/usr/bin/env python3

"""
Static extraction of a script's argparse options for the web GUI.

The GUI must not import or run a script just to learn its flags (14 Webex
scripts execute their whole body at import time, and every script prompts),
so this walks the AST for parser.add_argument(...) calls instead. Only
literal arguments are understood; anything dynamic degrades to a plain
text field or is skipped, and the GUI keeps a free-text "additional
arguments" box for whatever this misses.
"""

import ast
from pathlib import Path
from typing import Any, List, Optional

_STORE_ACTIONS = {"store", "store_true", "store_false", "store_const", "append", "count"}


def _literal(node: Optional[ast.AST]) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _type_name(node: Optional[ast.AST]) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _stringify(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None if value is None else str(value).lower()
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value)


def extract_options(path: Path) -> List[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return []

    options: List[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue

        flags = [a for a in (_literal(arg) for arg in node.args) if isinstance(a, str)]
        if not flags:
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}

        positional = not flags[0].startswith("-")
        action = _literal(kw.get("action")) or "store"
        if action == "help":
            continue
        dest = _literal(kw.get("dest"))
        if not dest:
            longest = max(flags, key=len)
            dest = longest.lstrip("-").replace("-", "_")

        choices = _literal(kw.get("choices"))
        if choices is not None:
            choices = [str(c) for c in choices]

        options.append({
            "flags": flags,
            "dest": dest,
            "positional": positional,
            "action": action if action in _STORE_ACTIONS else "store",
            "help": _literal(kw.get("help")),
            "default": _stringify(_literal(kw.get("default"))),
            "choices": choices,
            "required": bool(_literal(kw.get("required"))) or positional,
            "type": _type_name(kw.get("type")),
            "nargs": _stringify(_literal(kw.get("nargs"))),
            "metavar": _literal(kw.get("metavar")),
        })
    return options
