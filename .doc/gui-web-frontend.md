# Web GUI (`python3 main.py --gui`): Design Notes

Audience: whoever next modifies `gui/backend/*` or `gui/frontend/*`, human or
Claude. Companion to `.doc/main-py-launcher.md`; read that one first, its
Section 3 (the subprocess constraint) applies here unchanged.

## 1. What it is

A browser front end for the same script inventory `main.py` shows in the
terminal. FastAPI serves a JSON API plus the compiled React app; React draws
the "slab42 UC-Automations" landing page, a left menu (CUCM / CUC / CUBE /
Webex, each expanding to its scripts, plus Settings), a docstring popover on
hover that expands to full frame on click, and a script page where the
script runs **entirely through web forms**: argparse flags become an
options form, every `input()`/`getpass()` prompt the script makes appears
as a typed form field (yes/no buttons, numbered choice list, password
field, CSV picker with upload, Continue button, or text), and plain output
scrolls in an activity log. There is no terminal emulator anywhere.

```
python3 main.py --gui                 # http://127.0.0.1:8420/
python3 main.py --gui --port 9000
python3 main.py --gui --host 0.0.0.0  # only behind an authenticating proxy
```

First-time build of the frontend (Node 18+):

```
cd gui/frontend && npm install && npm run build
```

`gui/frontend/dist/` is git-ignored. Without it the API still answers and
`/` returns a 503 JSON hint telling you to build.

Development loop: `python3 main.py --gui` in one shell, `npm run dev` in
`gui/frontend` in another. Vite proxies `/api` and `/ws` to port 8420.

## 2. Architecture

| Piece | Owns |
|---|---|
| `main.py --gui` | Parses `--host/--port`, imports `gui.backend.app.serve`, prints an install hint if FastAPI is missing. |
| `gui/backend/app.py` | FastAPI app. `/api/scripts` wraps `setup.script_registry.discover()` and `read_description()` (no separate registry, no cache: every request re-walks the four category dirs, same as the terminal menu). `/api/credentials*` and `/api/inventory`. Static `dist/` with SPA fallback. |
| `gui/backend/runner.py` | One child process per WebSocket on plain pipes (`asyncio.create_subprocess_exec`, stderr merged into stdout, `start_new_session=True`, `cwd=entry.path.parent`, argv `[sys.executable, script, *shlex.split(args)]`). Splits stdout into text and prompt markers, classifies each prompt, forwards answers to stdin as one line each. Closing the socket sends SIGTERM to the process group, then SIGKILL after 3 s. |
| `gui/backend/shim/sitecustomize.py` | Put first on the child's `PYTHONPATH`, so Python imports it before the script runs. When `UC_GUI=1` it replaces `builtins.input` and `getpass.getpass` with versions that print the prompt, write a `\x00UCGUI:{json}\x00` marker line, then block on stdin as before. Scripts are not modified. |
| `gui/backend/prompts.py` | Heuristic classifier: prompt text + the output printed since the previous prompt -> `{kind, label, default, choices, suggestions, allow_other}`. Falls back to a text field when unsure; the answer is always written verbatim, so a wrong guess never blocks a run. |
| `gui/backend/argspec.py` | AST walk for `parser.add_argument(...)` literals -> `options[]` on the script object. Never imports or runs the script. |
| `gui/backend/ini_editor.py` | Line-preserving editor for `.env/credentials.env`. Never returns secret values, only whether each is set. Atomic write (`.tmp` + `os.replace`, mode 0600). |
| `gui/frontend/` | Vite + React 18 + TypeScript, `react-router-dom`, `@xterm/xterm` + `@xterm/addon-fit`. Routes: `/`, `/scripts/<rel>`, `/settings`. |

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{status, root, python, frontend_built}` |
| GET | `/api/scripts` | `{categories:[{label,dir,description,scripts:[{rel,filename,title,category,takes_args,description}]}], skipped:[{rel,reason}]}` |
| GET | `/api/scripts/{rel}` | one script, 404 if not launchable |
| WS | `/ws/run/{rel}?args=` | server sends `{type:started,pid,command}`, `{type:output,data}`, `{type:prompt,id,text,label,kind,secret,default,choices[],suggestions[],allow_other}`, `{type:exit,code}` then closes, or `{type:error,message}`; client sends `{type:answer,id,value}` / `{type:kill}`. `kind` is `text`, `secret`, `yes_no`, `choice`, `file` or `continue`. |
| GET | `/api/data-files` | `.csv/.txt/.xlsx` files in `_DATA/` with `path` as the script sees it (`../_DATA/<name>`) |
| POST | `/api/data-files?overwrite=` | multipart `file` upload into `_DATA/` (plain names only, 409 if it exists) |
| GET | `/api/data-files/{name}` | download, e.g. a report a script wrote |
| GET | `/api/credentials` | `{path, exists, sections:[{section,service,identifier,fields:{username},secrets:{password:bool}}]}` |
| PUT | `/api/credentials/{section}` | `{fields:{...}, secrets:{password:{action:keep|set|clear, value}}}`; creates the section if missing |
| DELETE | `/api/credentials/{section}` | 204 |
| GET | `/api/inventory` | clusters.csv and routers.csv rows (names for the Settings identifier suggestions) |
| GET | `/api/docs` | Swagger UI |

## 3. Why a shim on pipes and not a terminal

`.doc/main-py-launcher.md` Section 3 forbids capturing stdio in the
terminal launcher because 42 of 48 scripts call `input()` and passwords go
through `getpass()`. The first GUI build kept those semantics with a PTY and
xterm.js. The user then asked for every option to be a web control with no
CLI window, which needs the server to know *when* a script is waiting and
*what* it asked. Guessing that from a PTY byte stream is fragile, so the
child instead loads `shim/sitecustomize.py` via `PYTHONPATH`. Python
imports `sitecustomize` at start-up for any interpreter, virtualenv or not,
so the script file itself is untouched and still runs identically from the
terminal menu, where `UC_GUI` is unset and the shim is not on the path.

The marker rides inside stdout on purpose: it is emitted right after the
prompt text on the same stream, so the backend never has to reconcile the
order of two pipes when it parses the numbered list that preceded a
"Select cluster [1-N]:" prompt. NUL bytes make it unambiguous.

Everything else from Section 3 still holds: no `runpy`, no `import`, no
`exec()`, no `shell=True`. `start_new_session=True` is used here **on
purpose**, the opposite of the terminal launcher, because the browser has
no Ctrl-C to forward; the process group is what lets "Stop" and
socket-close kill the whole tree. Secrets: `getpass()` answers are echoed
to the log as `********` and never appear in output.

Known limits: a script that reads `sys.stdin` directly (none do today) or
spawns a sub-process that prompts (none do) would block without a form;
"Stop" is the way out. Classification is heuristic, see `prompts.py`
docstring for the recognised conventions and keep new scripts to them.

## 4. Security posture

- The GUI can run any script in the repo as the user who started the
  server. It binds to `127.0.0.1` by default. `--host 0.0.0.0` is only
  acceptable behind something that authenticates (SSO proxy, SSH tunnel).
  There is deliberately no auth layer inside the app to keep it honest
  about that.
- Secrets in `credentials.env` never leave the server. The API reports
  `set`/`blank`, the Settings form only ever sends a new value, "keep", or
  "clear".
- `rel` in `/api/scripts/{rel}` and `/ws/run/{rel}` is matched against the
  registry, never used as a filesystem path, so nothing outside the four
  category dirs can be launched. The SPA fallback refuses paths that
  resolve outside `dist/`.

## 5. Behaviour the frontend relies on

- Script identity is the repo-relative path (`rel`), same key the terminal
  launcher uses for favorites. Retitling a script does not break links.
- Descriptions are the docstring via `read_description()`; `null` when a
  script has none (currently the 8 Webex scripts without a docstring).
- `takes_args` drives whether the Options card is shown; `options[]` (from
  `argspec.py`) drives its fields, and an "Additional arguments" box covers
  anything static analysis missed (`cucm/em_bulk_login.py` reads `sys.argv`
  by hand and gets only that box). Args are split with `shlex.split`, so
  quote as you would in a shell.
- File prompts offer `_DATA/` files as `../_DATA/<name>` because the script's
  cwd is its own directory. Leaving the field blank sends an empty line and
  the script applies its own `[default]`.
- Exit code semantics: the script's own code; death by signal N is reported
  as `128 + N`; a socket closed mid-run kills the child and sends no `exit`.

## 6. Changelog

**2026-09-28**: Initial build on branch `GUI-add-on`: `main.py --gui`,
`gui/backend/` (FastAPI, PTY runner, credentials editor),
`gui/frontend/` (React), this doc.

**2026-09-28 (later)**: Terminal removed at the user's request. PTY runner
replaced by the `sitecustomize` prompt shim on pipes, prompt classifier,
argparse options form, `_DATA` file list/upload/download. xterm.js dropped
from the frontend.
