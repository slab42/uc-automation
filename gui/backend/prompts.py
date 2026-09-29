#!/usr/bin/env python3

"""
Turns a raw input()/getpass() prompt string, plus the script output that
preceded it, into a typed form field for the browser.

Everything here is heuristic and only affects presentation: whatever the
browser sends back is written to the script's stdin as a line, exactly as
if it had been typed. When the classifier is unsure it falls back to a
plain text field, so a wrong guess never blocks a run.

Prompt conventions recognised (see setup/prompt_utils.py and
setup/multi_object_loader.py for where they come from):
  "Question? (Y/n): " / "(y/N): "         -> yes_no with a default
  "Select cluster [1-8]: " after a numbered list -> choice
  "Enter CSV file name or full path [_DATA/x.csv]: " -> file with default
  "Press Enter to continue... "            -> continue
  getpass(), or 'password'/'token' in the prompt -> secret
  anything with a trailing [default]      -> text with default
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\r")
_YES_NO_RE = re.compile(r"\(\s*(Y/n|y/N|y/n|Y/N)\s*\)\s*:?\s*$")
_BRACKET_DEFAULT_RE = re.compile(r"\[(?:default:\s*)?([^\]]*)\]\s*:?\s*$", re.IGNORECASE)
_RANGE_RE = re.compile(r"\[\s*1\s*-\s*(\d+)\s*\]")
_NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
_SELECT_WORDS = re.compile(r"\b(select|selection|choose|choice|option|mode)\b", re.IGNORECASE)
_FILE_WORDS = re.compile(r"\b(csv|file|path|template|workbook|xlsx)\b", re.IGNORECASE)
_SLASH_LIST_RE = re.compile(r"\(([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)+)\)")
_SECRET_WORDS = re.compile(r"\b(password|passphrase|token|secret|pin)\b", re.IGNORECASE)
_DATA_EXTS = {".csv", ".txt", ".xlsx", ".json"}


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _clean_label(prompt: str) -> str:
    label = strip_ansi(prompt).strip()
    label = _YES_NO_RE.sub("", label).strip()
    label = _BRACKET_DEFAULT_RE.sub("", label).strip()
    label = re.sub(r"\s*\(1-\d+\)\s*$", "", label)
    label = label.rstrip(":").strip()
    return label or "Input"


def _numbered_choices(recent_output: str, prompt: str) -> List[Dict[str, str]]:
    """Collect '  1. Something' lines from the output since the last prompt."""
    choices: List[Dict[str, str]] = []
    seen = set()
    text = strip_ansi(recent_output)
    prompt_line = strip_ansi(prompt).strip()
    for line in text.splitlines():
        if line.strip() == prompt_line:
            continue
        m = _NUMBERED_RE.match(line)
        if not m:
            continue
        value, label = m.group(1), re.sub(r"\s{2,}", "  ", m.group(2))
        if value in seen:
            # A second numbered block started (e.g. two lists on screen);
            # keep the later one because it is what the prompt refers to.
            choices = []
            seen = set()
        seen.add(value)
        choices.append({"value": value, "label": label})
    return choices


def data_file_suggestions(root: Path) -> List[Dict[str, str]]:
    """Files under _DATA/ the user can pick for a file prompt.

    Scripts run with cwd = their own directory, so '../_DATA/<name>' is the
    path that resolves for them; that is what goes in 'value'.
    """
    data_dir = root / "_DATA"
    if not data_dir.is_dir():
        return []
    out = []
    for p in sorted(data_dir.iterdir(), key=lambda p: p.name.lower()):
        if p.is_file() and p.suffix.lower() in _DATA_EXTS and not p.name.startswith("."):
            out.append({"value": f"../_DATA/{p.name}", "label": p.name})
    for p in sorted((data_dir / "examples").glob("*"), key=lambda p: p.name.lower()) \
            if (data_dir / "examples").is_dir() else []:
        if p.is_file() and p.suffix.lower() in _DATA_EXTS:
            out.append({"value": f"../_DATA/examples/{p.name}", "label": f"examples/{p.name}"})
    return out


def classify(prompt: str, secret: bool, recent_output: str, root: Path,
             prompt_id: int) -> dict:
    """Build the 'prompt' WebSocket message for one pending input() call."""
    raw = strip_ansi(prompt)
    lower = raw.lower()
    default = ""
    m = _BRACKET_DEFAULT_RE.search(raw)
    if m:
        default = m.group(1).strip()

    msg = {
        "type": "prompt",
        "id": prompt_id,
        "text": raw,
        "label": _clean_label(raw),
        "kind": "text",
        "secret": False,
        "default": default,
        "choices": [],
        "suggestions": [],
        "allow_other": False,
    }

    if secret or _SECRET_WORDS.search(raw):
        msg.update(kind="secret", secret=True, default="")
        return msg

    yn = _YES_NO_RE.search(raw)
    if yn:
        token = yn.group(1)
        msg.update(kind="yes_no",
                   default="y" if token in ("Y/n",) else ("n" if token == "y/N" else ""),
                   choices=[{"value": "y", "label": "Yes"}, {"value": "n", "label": "No"}])
        return msg

    if lower.strip().startswith("press enter") and " or " not in lower:
        msg.update(kind="continue", label=_clean_label(raw).rstrip(". "))
        return msg

    choices = _numbered_choices(recent_output, raw)
    rng = _RANGE_RE.search(raw)
    looks_like_select = bool(rng) or bool(_SELECT_WORDS.search(raw)) or "1 or 2" in raw
    if choices and looks_like_select:
        if rng:
            n = int(rng.group(1))
            if len(choices) > n:
                choices = choices[-n:]
        msg.update(kind="choice", choices=choices,
                   allow_other=("command" in lower or "or " in lower and "[" not in lower))
        if default and default not in {c["value"] for c in choices}:
            msg["default"] = ""
        return msg
    if "1 or 2" in raw and not choices:
        msg.update(kind="choice",
                   choices=[{"value": "1", "label": "1"}, {"value": "2", "label": "2"}])
        return msg

    if _FILE_WORDS.search(raw):
        msg.update(kind="file", suggestions=data_file_suggestions(root))
        return msg

    # "Select operation mode (login/logout/check) [login]: " -> pick one word
    sl = _SLASH_LIST_RE.search(raw)
    if sl and not _YES_NO_RE.search(raw):
        words = sl.group(1).split("/")
        if 2 <= len(words) <= 8:
            msg.update(kind="choice", allow_other=True,
                       choices=[{"value": w, "label": w} for w in words],
                       label=_clean_label(_SLASH_LIST_RE.sub("", raw)))
            return msg

    return msg
