#!/usr/bin/env python3

"""
FastAPI application for the slab42 UC-Automations web GUI.

Exposes the same script inventory as `python3 main.py` (via
setup/script_registry.discover), runs a chosen script in a PTY over a
WebSocket, and edits .env/credentials.env for the Settings page. The
compiled React app in gui/frontend/dist is served as static files with an
SPA fallback.

Started with `python3 main.py --gui` (see main.py for --host/--port).
Binds to 127.0.0.1 by default: the GUI can run any script in the repo with
the server's privileges, so never expose it on a network without putting an
authenticating proxy in front of it.
"""

import datetime as _dt
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from setup.multi_object_loader import read_clusters_csv, read_routers_csv  # noqa: E402
from setup.script_registry import CATEGORIES, ScriptEntry, discover, read_description  # noqa: E402

from gui.backend import ini_editor  # noqa: E402
from gui.backend.argspec import extract_options  # noqa: E402
from gui.backend.runner import run_over_websocket  # noqa: E402

FRONTEND_DIST = ROOT / "gui" / "frontend" / "dist"
CREDENTIALS_PATH = ROOT / ".env" / "credentials.env"
DATA_DIR = ROOT / "_DATA"
_DATA_UPLOAD_EXTS = {".csv", ".txt", ".xlsx"}
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}$")


# -- script inventory -----------------------------------------------------

def _entry_to_dict(entry: ScriptEntry, with_description: bool = True) -> dict:
    options = extract_options(entry.path) if entry.takes_args else []
    return {
        "rel": entry.rel,
        "filename": entry.path.name,
        "title": entry.title,
        "category": entry.category,
        "takes_args": entry.takes_args,
        "argparse": bool(options),
        "options": options,
        "description": read_description(entry.path) if with_description else None,
    }


def _data_file_entry(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": f"../_DATA/{path.name}",
        "size": stat.st_size,
        "modified": _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def _safe_data_name(name: str) -> Path:
    name = Path(name or "").name
    if not _SAFE_NAME_RE.match(name) or Path(name).suffix.lower() not in _DATA_UPLOAD_EXTS:
        raise HTTPException(status_code=400,
                            detail="File name must be a plain .csv, .txt or .xlsx name")
    return DATA_DIR / name


def _find_entry(rel: str) -> Optional[ScriptEntry]:
    rel = unquote(rel).strip("/")
    entries, _skipped = discover(ROOT)
    for entry in entries:
        if entry.rel == rel:
            return entry
    return None


# -- credentials models ---------------------------------------------------

class SecretChange(BaseModel):
    action: str = Field(pattern="^(keep|set|clear)$")
    value: Optional[str] = None


class SectionUpdate(BaseModel):
    fields: Dict[str, str] = Field(default_factory=dict)
    secrets: Dict[str, SecretChange] = Field(default_factory=dict)


def _section_view(section: str) -> dict:
    for sec in ini_editor.read_sections(CREDENTIALS_PATH):
        if sec["section"] == section:
            return sec
    raise HTTPException(status_code=404, detail=f"Section {section} not found")


def create_app() -> FastAPI:
    app = FastAPI(title="slab42 UC-Automations", docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "root": str(ROOT),
                "python": sys.version.split()[0],
                "frontend_built": (FRONTEND_DIST / "index.html").exists()}

    @app.get("/api/scripts")
    def list_scripts() -> dict:
        entries, skipped = discover(ROOT)
        by_cat: Dict[str, List[dict]] = {label: [] for label, _, _ in CATEGORIES}
        for entry in entries:
            by_cat.setdefault(entry.category, []).append(_entry_to_dict(entry))
        return {
            "categories": [
                {"label": label, "dir": dirname, "description": desc,
                 "scripts": by_cat.get(label, [])}
                for label, dirname, desc in CATEGORIES
            ],
            "skipped": [{"rel": rel, "reason": reason} for rel, reason in skipped],
        }

    @app.get("/api/scripts/{rel:path}")
    def get_script(rel: str) -> dict:
        entry = _find_entry(rel)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"No launchable script at {rel}")
        return _entry_to_dict(entry)

    @app.websocket("/ws/run/{rel:path}")
    async def run_script(ws: WebSocket, rel: str, args: str = Query(default="")) -> None:
        await ws.accept()
        entry = _find_entry(rel)
        if entry is None:
            await ws.send_json({"type": "error", "message": f"No launchable script at {rel}"})
            await ws.close()
            return
        await run_over_websocket(ws, entry, args)

    # -- _DATA files (CSV inputs and report outputs) ------------------------

    @app.get("/api/data-files")
    def list_data_files() -> dict:
        files = []
        if DATA_DIR.is_dir():
            for p in sorted(DATA_DIR.iterdir(), key=lambda p: p.name.lower()):
                if p.is_file() and p.suffix.lower() in _DATA_UPLOAD_EXTS and not p.name.startswith("."):
                    files.append(_data_file_entry(p))
        return {"dir": "_DATA", "files": files}

    @app.get("/api/data-files/{name}")
    def download_data_file(name: str) -> FileResponse:
        target = _safe_data_name(unquote(name))
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"{target.name} not found in _DATA")
        return FileResponse(str(target), filename=target.name)

    @app.post("/api/data-files", status_code=201)
    def upload_data_file(file: UploadFile = File(...),
                         overwrite: bool = Query(default=False)) -> dict:
        target = _safe_data_name(file.filename or "")
        if target.exists() and not overwrite:
            raise HTTPException(status_code=409,
                                detail=f"{target.name} already exists in _DATA")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".uploading")
        try:
            with tmp.open("wb") as out:
                shutil.copyfileobj(file.file, out)
            tmp.replace(target)
        finally:
            if tmp.exists():
                tmp.unlink()
        return _data_file_entry(target)

    # -- credentials -------------------------------------------------------

    @app.get("/api/credentials")
    def list_credentials() -> dict:
        return {
            "path": str(CREDENTIALS_PATH.relative_to(ROOT)),
            "exists": CREDENTIALS_PATH.exists(),
            "sections": ini_editor.read_sections(CREDENTIALS_PATH),
        }

    @app.put("/api/credentials/{section}")
    def update_credentials(section: str, body: SectionUpdate) -> dict:
        section = unquote(section)
        try:
            service, _identifier = ini_editor.validate_section_name(section)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        values: Dict[str, Optional[str]] = {}
        for key, value in body.fields.items():
            key = key.strip().lower()
            if not key or key in ini_editor.SECRET_KEYS:
                raise HTTPException(status_code=400,
                                    detail=f"{key!r} must be sent under 'secrets'")
            values[key] = value.strip()
        for key, change in body.secrets.items():
            key = key.strip().lower()
            if key not in ini_editor.SECRET_KEYS:
                raise HTTPException(status_code=400,
                                    detail=f"{key!r} is not a secret key")
            if change.action == "keep":
                values[key] = None
            elif change.action == "clear":
                values[key] = ""
            else:
                if change.value is None:
                    raise HTTPException(status_code=400,
                                        detail=f"'set' for {key} needs a value")
                if "\n" in change.value or "\r" in change.value:
                    raise HTTPException(status_code=400,
                                        detail="Secret values cannot contain newlines")
                values[key] = change.value

        exists = any(s["section"] == section
                     for s in ini_editor.read_sections(CREDENTIALS_PATH))
        if not exists:
            # A brand-new section must at least materialise its expected keys
            # so the CLI loaders find them (blank password prompts at runtime).
            default_secret = "api_token" if service == "WEBEX" else "password"
            values.setdefault(default_secret, "")
            if service != "WEBEX":
                values.setdefault("username", "")
            values = {k: ("" if v is None else v) for k, v in values.items()}

        ini_editor.upsert_section(CREDENTIALS_PATH, section, values)
        return _section_view(section)

    @app.delete("/api/credentials/{section}", status_code=204)
    def delete_credentials(section: str) -> Response:
        section = unquote(section)
        try:
            ini_editor.validate_section_name(section)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not ini_editor.delete_section(CREDENTIALS_PATH, section):
            raise HTTPException(status_code=404, detail=f"Section {section} not found")
        return Response(status_code=204)

    @app.get("/api/inventory")
    def inventory() -> dict:
        return {
            "clusters": read_clusters_csv(ROOT / "_DATA" / "clusters.csv"),
            "routers": read_routers_csv(ROOT / "_DATA" / "routers.csv"),
        }

    # -- static frontend with SPA fallback ---------------------------------

    if (FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404)
        index = FRONTEND_DIST / "index.html"
        if not index.exists():
            return JSONResponse(status_code=503, content={
                "detail": "Frontend not built. Run: cd gui/frontend && npm install && npm run build"})
        candidate = (FRONTEND_DIST / full_path) if full_path else index
        try:
            candidate.resolve().relative_to(FRONTEND_DIST.resolve())
        except ValueError:
            raise HTTPException(status_code=404)
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))

    return app


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8420, reload: bool = False) -> int:
    import uvicorn

    if not (FRONTEND_DIST / "index.html").exists():
        print("Note: gui/frontend/dist is missing. The API will run, but the web UI "
              "needs a build first:\n  cd gui/frontend && npm install && npm run build")
    print(f"slab42 UC-Automations GUI: http://{host}:{port}/  (Ctrl-C to stop)")
    uvicorn.run("gui.backend.app:app", host=host, port=port, reload=reload,
                log_level="info")
    return 0
