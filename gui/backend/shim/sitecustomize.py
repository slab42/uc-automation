#!/usr/bin/env python3

"""
Prompt shim loaded into every script the web GUI launches.

gui/backend/runner.py puts this directory first on PYTHONPATH, so Python's
site machinery imports it at interpreter start-up, before the script runs.
It replaces builtins.input() and getpass.getpass() with versions that still
print the prompt and still block on stdin, but first write a one-line
marker to stdout so the backend knows a prompt is pending and can show it
as a form field in the browser. Outside the GUI this file is never on the
path and nothing here runs.

The marker is a line of the form  \\x00UCGUI:{json}\\x00  - NUL bytes never
appear in normal script output, which is what makes it safe to parse out.
"""

import builtins
import json
import os
import sys

_MARK_START = "\x00UCGUI:"
_MARK_END = "\x00\n"
_counter = 0


def _emit(prompt: str, secret: bool) -> None:
    global _counter
    _counter += 1
    payload = {"id": _counter, "prompt": prompt, "secret": secret}
    try:
        sys.stdout.write(prompt)
        sys.stdout.write(_MARK_START + json.dumps(payload) + _MARK_END)
        sys.stdout.flush()
    except Exception:  # never let the shim break the script
        pass


def _read_line() -> str:
    line = sys.stdin.readline()
    if not line:
        raise EOFError("EOF when reading a line")
    return line.rstrip("\r\n")


def _gui_input(prompt: object = "") -> str:
    _emit(str(prompt), secret=False)
    return _read_line()


def _gui_getpass(prompt: object = "Password: ", stream=None) -> str:
    _emit(str(prompt), secret=True)
    return _read_line()


if os.environ.get("UC_GUI") == "1":
    builtins.input = _gui_input
    try:
        import getpass as _getpass
        _getpass.getpass = _gui_getpass
    except Exception:
        pass
