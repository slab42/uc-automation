#!/usr/bin/env python3

"""
Form-driven script runner for the web GUI.

Each WebSocket connection to /ws/run/<rel> starts exactly one automation
script as a real child process. The child runs with gui/backend/shim on
PYTHONPATH, so its input()/getpass() calls print a marker line before they
block (see shim/sitecustomize.py). This module watches stdout for those
markers, classifies each pending prompt (gui/backend/prompts.py) and sends
it to the browser as a typed form field; the browser's answer is written
to the child's stdin as one line. Plain output is forwarded as text with
ANSI escapes stripped. There is no terminal emulator anywhere in the path.

The constraints from .doc/main-py-launcher.md section 3 still hold: the
script is never imported or exec()'d by the server, its cwd is its own
directory, argv[0] is the script path, and stdio is a real pipe the script
reads with input() exactly as it always did.
"""

import asyncio
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from setup.script_registry import ScriptEntry

from gui.backend.prompts import classify, strip_ansi

ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = Path(__file__).resolve().parent / "shim"

_KILL_GRACE_SECONDS = 3.0
_MARK_RE = re.compile(r"\x00UCGUI:(\{.*?\})\x00\n?")
_RECENT_LIMIT = 20000  # chars of output kept for choice-list parsing


def build_command(entry: ScriptEntry, args: str) -> List[str]:
    extra = shlex.split(args) if args else []
    return [sys.executable, str(entry.path), *extra]


def build_env() -> dict:
    env = dict(os.environ)
    shim = str(SHIM_DIR)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = shim if not existing else f"{shim}{os.pathsep}{existing}"
    env["PYTHONUNBUFFERED"] = "1"
    env["UC_GUI"] = "1"
    env["UC_LAUNCHER_NO_CLEAR"] = "1"
    env["TERM"] = "dumb"
    env.pop("PYTHONSTARTUP", None)
    return env


class ScriptProcess:
    """One running script on pipes."""

    def __init__(self, entry: ScriptEntry, args: str):
        self.entry = entry
        self.args = args
        self.proc: Optional[asyncio.subprocess.Process] = None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *build_command(self.entry, self.args),
            cwd=str(self.entry.path.parent),
            env=build_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def write_line(self, value: str) -> None:
        if self.proc and self.proc.stdin and not self.proc.stdin.is_closing():
            self.proc.stdin.write((value + "\n").encode("utf-8"))

    async def terminate(self) -> None:
        if not self.alive():
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                self.proc.terminate()
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(self.proc.wait(), _KILL_GRACE_SECONDS)
        except asyncio.TimeoutError:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self.proc.kill()
            await self.proc.wait()

    def close_stdin(self) -> None:
        if self.proc and self.proc.stdin and not self.proc.stdin.is_closing():
            try:
                self.proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass


def _swallow_result(task: "asyncio.Task") -> None:
    if not task.cancelled():
        task.exception()


async def _send(ws: WebSocket, payload: dict) -> None:
    if ws.client_state == WebSocketState.CONNECTED:
        await ws.send_text(json.dumps(payload))


class _OutputParser:
    """Splits the child's stdout into plain text and prompt markers."""

    def __init__(self):
        self.buffer = ""
        self.recent = ""

    def feed(self, chunk: str):
        """Yield ('output', text) and ('prompt', dict) events."""
        self.buffer += chunk
        while True:
            m = _MARK_RE.search(self.buffer)
            if m:
                before, after = self.buffer[:m.start()], self.buffer[m.end():]
                if before:
                    self.recent += before
                    yield ("output", strip_ansi(before))
                try:
                    yield ("prompt", json.loads(m.group(1)))
                except json.JSONDecodeError:
                    pass
                self.buffer = after
                continue
            # No complete marker. Emit everything up to a possible partial
            # marker start so output streams live but the marker never splits.
            cut = self.buffer.rfind("\x00")
            if cut == -1:
                text, self.buffer = self.buffer, ""
            else:
                text, self.buffer = self.buffer[:cut], self.buffer[cut:]
            if text:
                self.recent += text
                yield ("output", strip_ansi(text))
            break
        if len(self.recent) > _RECENT_LIMIT:
            self.recent = self.recent[-_RECENT_LIMIT:]

    def flush(self):
        if self.buffer:
            text, self.buffer = self.buffer.replace("\x00", ""), ""
            if text:
                yield ("output", strip_ansi(text))

    def take_recent(self) -> str:
        recent, self.recent = self.recent, ""
        return recent


async def run_over_websocket(ws: WebSocket, entry: ScriptEntry, args: str) -> None:
    """Drive one script for the lifetime of one WebSocket connection."""
    process = ScriptProcess(entry, args)
    try:
        await process.start()
    except Exception as exc:  # noqa: BLE001 - report anything to the browser
        await _send(ws, {"type": "error", "message": f"Failed to start: {exc}"})
        return

    await _send(ws, {"type": "started", "pid": process.proc.pid,
                     "command": build_command(entry, args)})

    parser = _OutputParser()
    pending: dict = {}  # id -> prompt meta (secret flag) awaiting an answer

    async def pump_output() -> None:
        import codecs
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        stream = process.proc.stdout
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            for kind, payload in parser.feed(decoder.decode(chunk)):
                if kind == "output":
                    await _send(ws, {"type": "output", "data": payload})
                else:
                    msg = classify(payload.get("prompt", ""), bool(payload.get("secret")),
                                   parser.take_recent(), ROOT, int(payload.get("id", 0)))
                    pending[msg["id"]] = msg
                    await _send(ws, msg)
        for kind, payload in parser.flush():
            await _send(ws, {"type": "output", "data": payload})

    async def pump_input() -> None:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "answer":
                prompt = pending.pop(int(msg.get("id", -1)), None)
                value = str(msg.get("value", "")).replace("\r", "").replace("\n", "")
                echo = "********" if (prompt or {}).get("secret") else value
                await _send(ws, {"type": "output", "data": f"{echo}\n"})
                try:
                    process.write_line(value)
                except (OSError, RuntimeError):
                    return
            elif kind == "kill":
                await process.terminate()

    output_task = asyncio.create_task(pump_output())
    input_task = asyncio.create_task(pump_input())
    for task in (output_task, input_task):
        # Consume the result whenever the task ends (a WebSocketDisconnect
        # is expected here) so asyncio never logs "exception was never
        # retrieved". Do not await the tasks: under some ASGI servers a
        # cancelled receive_text() only settles once the socket closes.
        task.add_done_callback(_swallow_result)
    disconnected = False
    try:
        done, _ = await asyncio.wait({output_task, input_task},
                                     return_when=asyncio.FIRST_COMPLETED)
        if input_task in done:
            disconnected = True
            await process.terminate()
        else:
            await process.proc.wait()
    finally:
        for task in (output_task, input_task):
            if not task.done():
                task.cancel()
        await process.terminate()
        process.close_stdin()

    code = process.proc.returncode
    if code is None:
        code = -1
    elif code < 0:
        code = 128 - code  # signal death, shell-style
    if not disconnected:
        await _send(ws, {"type": "exit", "code": code})
        try:
            await ws.close()
        except RuntimeError:
            pass
