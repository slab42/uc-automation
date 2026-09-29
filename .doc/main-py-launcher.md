# main.py Launcher — Design Notes

Audience: whoever next modifies `main.py`, `setup/script_registry.py`,
`setup/launcher_config.py`, or `setup/menu.py` — human or Claude. Purpose:
let you make changes without re-reading all 48 automation scripts.

## 1. Purpose and how to use

Read this before changing the launcher. The code is the source of truth;
this explains why it is shaped the way it is, especially the parts that
look over-engineered until you know the reason (Section 3).

- Entry point: `python3 main.py` (interactive menu), `python3 main.py --list`
  (plain-text inventory, safe to pipe), `--list --verbose` (also shows
  skipped files and duplicate-title warnings), `--no-clear` / `UC_LAUNCHER_NO_CLEAR=1`.
- **Discovery is never cached.** `setup/script_registry.discover()` re-walks
  the four category directories every time the launcher starts, and again
  whenever the user presses `r`. Consequences:
  - Editing a `# TITLE:` line shows up on next launch or `r` — no restart needed beyond that.
  - Deleting/losing a title removes the script from the menu immediately and
    increments the "no # TITLE:" advisory count on the main menu.
  - Adding a new titled script makes it appear with zero registration steps.
  - Favorites and hidden marks are keyed by the script's **repo-relative path**,
    never by title, so retitling a script preserves its favorite/hidden state.
- If you change discovery, config schema, or the subprocess launch, update
  this doc in the same commit (see Section 5 and CLAUDE.md).

## 2. Architecture

| Module | Owns |
|---|---|
| `main.py` | CLI parsing (`--list`, `--verbose`, `--no-clear`), puts repo root on `sys.path`, delegates to `discover()` for `--list` or `menu.run()` for the interactive menu. |
| `setup/script_registry.py` | Discovery only, never runs anything. Walks `CATEGORIES` dirs, applies `_SKIP_DIR_PARTS` and `_DENYLIST`, reads `# TITLE:` (line scan) and description (AST), detects `takes_args`. Returns `(entries, skipped)`. |
| `setup/launcher_config.py` | Persistence of per-user state (`favorites`, `hidden`, `show_hidden`, `clear_screen`) to `.var/launcher.json`. Atomic save (`.tmp` + `os.replace`), quarantines corrupt JSON to `.bak`, `read_only` mode if the file's `version` is newer than this build understands. |
| `setup/menu.py` | All interactive screens (main / category / favorites), pagination, item commands (`i`/`f`/`x`/`a`), and the subprocess launch of the chosen script. |

## 3. The subprocess constraint (read this before "optimizing" anything)

Scripts are run as **child processes** (`subprocess.run` in
`setup/menu.py:_run_and_report`), never imported or `exec`'d in-process.
This must never be changed. Six verified reasons:

1. **26 scripts under `cucm/`** do a bare sibling import, `from ucmAPI import AXL`,
   which only resolves when the script's own directory is `sys.path[0]` —
   i.e. run as `python3 <name>.py` from inside `cucm/`. An in-process
   `import` uses the launcher's `sys.path`, not the script's directory, and breaks this.
2. Scripts use `basepath = Path.cwd()` and relative paths (`../_logs/...`,
   `basepath.parent / '_DATA' / 'clusters.csv'`) resolved against **their
   own** working directory. The child process is launched with
   `cwd=str(entry.path.parent)` for exactly this reason.
3. `sys.exit()` appears in 37 files / 86 call sites across `cucm/cuc/cube/webex`
   (verified 2026-09-28; the constant `SystemExit` in a shared process would
   kill the launcher, not just the script).
4. `setup/logger.py` uses a module-global `logging.getLogger('my_logger')`
   and **appends** a handler on every call. Two scripts sharing one process
   would duplicate every log line from the first script onward.
5. `setup/var_loader.py` derives its `.var` filename from `sys.argv[0]`.
   In-process, that would resolve to `.var/main.py.var` instead of the
   target script's own `.var` file.
6. All 14 top-level `webex/*.py` scripts have **no `if __name__ == "__main__"` guard** —
   their body runs at import time, with no way to control when/whether it runs.

**Forbidden constructs — grep for these before touching `setup/menu.py`:**

| Construct | Why it's wrong here |
|---|---|
| `runpy.run_path()` | Same in-process failure modes as `import` (reasons 1–6 above). |
| `import` of a target script | Same as above; also 14 webex scripts execute their body on import (reason 6). |
| `exec()` on script source | Same as above, plus loses the script's own `__file__`/`sys.argv[0]`. |
| `capture_output=` / `stdout=` / `stderr=` | Stdio must stay inherited: 42 of the 48 scripts call `input()` and 1 calls `getpass()` directly (the rest prompt through `setup/multi_object_loader.py`) — capturing stdio breaks every prompt. |
| `shell=True` | No shell interpretation needed, and 5 script filenames contain hyphens (e.g. `remedy-RP-oneoff.py`, `compare_advP-RP.py`) that a shell command line would need careful quoting for. |
| `start_new_session=True` | Would detach the child into its own process group, orphaning it from the launcher's Ctrl-C — a hung script would become unkillable instead of exiting with code 130. |
| `Path.cwd()` (in the launcher, for the child's cwd) | Resolves to the *launcher's* directory, not the script's — use `entry.path.parent` instead (reason 2). |

## 4. Verified codebase facts (re-verified 2026-09-28)

- **Counts** (via `python3 main.py --list`): CUCM 25, CUC 7, CUBE 2, Webex 14 — **total 48**.
- **`ast.get_docstring()` returns `None` for 11 files** scanned under
  `cucm/cuc/cube/webex` (excluding `DEV/`, `schema/`, `examples/`). Breakdown:
  - 3 denylisted CUCM support/probe files (`cucm/general.py` has no string at all;
    `cucm/find_css_table.py` and `cucm/test_css_schema.py` put `import warnings`
    before their description).
  - 8 Webex scripts have no string at all.
  - As of 2026-09-28 every live CUCM, CUC and CUBE script has its docstring as the
    first statement (the 13 live CUCM scripts that used to put `import warnings`
    above it were reordered). `read_description()` still falls back to scanning
    for the first bare string `Expr` because the two denylisted probes and any
    future slip would otherwise lose their `i` (details) text.
- **10 scripts** are flagged `takes_args=True` (shown as `[args]` in the menu):
  9 build an `argparse.ArgumentParser`; the 10th, `cucm/em_bulk_login.py`,
  instead indexes `sys.argv` directly for an undocumented-to-argparse
  positional `debug <device>` mode (`python3 em_bulk_login.py debug SEP...`).
  This is what the `a` (run with args) command exists for.
- **Denylist** (`_DENYLIST` in `script_registry.py`) and why:
  - `cucm/ucmAPI.py`, `cucm/general.py`, `cuc/cucAPI.py` — support modules, not runnable standalone.
  - `cucm/test_css_schema.py`, `cucm/find_css_table.py` — throwaway schema probes.
  - `setup/test_credentials_loader.py` — a test.
- **`webex/DEV/`** is excluded via `_SKIP_DIR_PARTS` as scratch/experimental
  work (16 files inside, none discovered). This exclusion is what let the
  design drop all nested-folder handling, breadcrumbs, and multi-level
  back-navigation — the menu is exactly two levels deep (main → category/favorites).
- **26 cucm scripts** (24 live + the 2 denylisted probes) use the bare
  `from ucmAPI import AXL` sibling import described in Section 3, and the **6 cuc
  scripts that talk to a server** use the equivalent bare `from cucAPI import CUC`
  (`cuc/build_call_trees.py` is offline and imports neither). Both only
  resolve when the child's cwd is the script's own directory.
- `sys.exit()` is 37 files / 86 call sites in the live scope; 42 files call
  `input()`; 1 file (`cube/check_router_mem_status.py`, its `--default` path)
  calls `getpass()` directly, every other password prompt goes through
  `setup/multi_object_loader.py`. Stdio must stay inherited (Section 3).
- Note on scope: every count here is over `cucm/`, `cuc/`, `cube/` and `webex/`,
  excluding `webex/DEV/`. Widening the scope changes them. State the scope
  whenever you quote a number, and re-verify rather than trusting any of these
  after scripts change.

## 5. Decision record

- **Subprocess over `runpy`/`import`.** See Section 3.
- **`# TITLE:` comment** over a PEP-257 docstring summary line or a
  `MENU_TITLE` module constant. Chosen because: a 5-line scan with no AST
  works even on a file with a syntax error; it's uniform across all 48
  scripts including the 8 with no docstring and the 15 with `import warnings`
  above the description; it disturbs no existing docstring text; and it
  matches the CLAUDE.md rule that script comments live at the top.
- **The title is an eligibility GATE, not a fallback chain.** A script
  without `# TITLE:` does not appear in the menu at all — no docstring
  fallback, no filename fallback. This makes the convention self-enforcing
  and guarantees no menu row is ever a truncated sentence. The cost: a
  script can vanish from the menu silently (e.g. a merge that clobbers the
  first 5 lines). That's why the main-menu "N scripts have no # TITLE: line"
  advisory and `--list --verbose` exist — **do not remove either.**
- **Favorites have three states, not two:** live (in the current registry),
  untitled-but-present (file exists on disk, just lost/never had its
  `# TITLE:` line — not stale, one edit restores it), and missing
  (file genuinely gone). An earlier version conflated the last two, reported
  an existing-but-untitled file as "no longer exists," and would **delete**
  the favorite if the user pressed `c`. `LauncherConfig.remove_stale_favorites()`
  now takes an explicit removal set for exactly this reason — do not change
  it to infer staleness on its own. This is a bug, not a design choice; do not reintroduce it.
- **`.var/launcher.json`** over a repo-root dotfile — groups it with other
  per-user, not-checked-in state already documented under `.var/` in CLAUDE.md.
- **Favorites + hide** over a hand-maintained curated manifest — auto-discovery
  means a new script appears with zero registration steps once it has a title.
- **`i` (details) key** over a pre-run confirmation screen — the scripts
  already have their own confirmation prompts, so a second one is just
  friction. `i` is the opt-in look-before-you-leap instead.
- **`?` for help, `x` for hide.** `h` is deliberately left unused — it reads
  as both "help" and "hide," so it was never bound to either.

## 6. Extending the launcher

**Add a category:** edit the `CATEGORIES` list in `setup/script_registry.py`
(tuple is `(menu label, directory name, description shown on main menu)`).
The directory must exist under the repo root and not collide with
`_SKIP_DIR_PARTS`.

**Change page size:** edit `ITEMS_PER_PAGE` in `setup/menu.py` (currently `9`).

**Current key map** (check this before adding a new key — collisions are easy):

| Key | Main menu | Category menu | Favorites menu |
|---|---|---|---|
| `1..N` | open category/Favorites | run script | run script |
| `?` | help | help | help |
| `r` | rescan | rescan | rescan |
| `0` | — | back to main menu | back to main menu |
| `q` | quit (confirm) | quit (confirm) | quit (confirm) |
| `n` / `p` | — | next / prev page | next / prev page |
| `i` | — | show details | show details |
| `f` | — | toggle favorite | toggle favorite |
| `x` | — | toggle hidden | not offered in help, but the shared two-step parser (`_TWO_STEP_RE`) still accepts `x<N>` here and will toggle hidden — undocumented, don't rely on it |
| `a` | — | run with args | run with args |
| `s` | — | toggle show-hidden | — |
| `c` | — | — | clear stale (missing) favorites, only shown when any exist |
| `<letter><digit>` | — | two-step shorthand, e.g. `f3` | two-step shorthand for `i`/`f`/`a` (and technically `x`, see above) |

**Add a command key:** pick an unused letter (not `h`). If it's an item-level
command, add it to `_TWO_STEP_RE`'s character class, `_ITEM_PROMPT_VERB`,
`_dispatch_item_command()`, the `choice in (...)` checks in both
`_category_menu()` and `_favorites_menu()`, and the relevant help text in `_show_help()`.

**Add a config field (backward compatible):** add the attribute + default in
`LauncherConfig._defaults()`, read it in `_load()` with `data.get('key', default)`
so old `launcher.json` files without the field just get the default, and
include it in the dict built in `_save()`. Only bump `CONFIG_VERSION` (currently `1`)
if an older launcher build reading the new field could silently misinterpret
or clobber it — `version > CONFIG_VERSION` makes the launcher run read-only
instead of overwriting a file it doesn't fully understand.

## 7. Changelog

**2026-09-24** — Initial build: `main.py` launcher added; `# TITLE:` convention
introduced across all 48 scripts; favorites/hidden persistence via
`.var/launcher.json`; title-as-gate behavior (no docstring/filename fallback).

**2026-09-28** — Standards audit: CUC and CUBE scripts brought to the CUCM
layout (docstring first, logger created first, `../_logs/` paths, cluster/router
selection only through `setup/multi_object_loader.py`); `cuc/cucAPI.py` added
and denylisted; 13 CUCM scripts reordered so the docstring precedes
`import warnings`; `cucm/lookup_device_type.py` logger call fixed. No launcher
code changed other than the denylist entry. Section 4 counts re-verified.
