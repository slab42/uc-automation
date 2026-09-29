# slab42 UC-Automations web GUI

Browser front end for the `main.py` launcher. Same scripts, same
`_DATA/` CSVs, same `.env/credentials.env`. Scripts run unchanged; every
prompt they make is shown as a web form field and their output as an
activity log. No terminal.

## Run

```bash
pip install -r requirements.txt          # adds fastapi + uvicorn
cd gui/frontend && npm install && npm run build && cd ../..   # once, needs Node 18+
python3 main.py --gui                    # http://127.0.0.1:8420/
```

Options: `--port N` (default 8420), `--host H` (default 127.0.0.1; only
change this behind an authenticating proxy or SSH tunnel, the GUI can run
any script in the repo).

## Develop

```bash
python3 main.py --gui        # backend on :8420
cd gui/frontend && npm run dev   # Vite dev server, proxies /api and /ws
```

Design notes and API contract: `.doc/gui-web-frontend.md`.
