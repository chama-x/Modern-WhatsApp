# WhatsApp MCP Server & Web UI

## Quick Start (Simplest Path)

Run: `make quick`  
This will: install dependencies (editable), seed demo data, start the API at http://localhost:8000

For live-reload development: `make quick-dev`  
Reset & reseed demo dataset: `make db-reset`  
Show all available commands: `make help`

Common targets:
- `make install` (pip editable install)
- `make db-seed` (ensure schema + demo data)
- `make run-api` (start API without reload)
- `make run-mcp` (run MCP stdio server)
- `make health` (hit /api/health)
- `make clean` (remove caches)

If you prefer not to use make:
1. `pip install -e .`
2. `python ../whatsapp-bridge/store/initialize_messages_db.py --seed`
3. `python api_server.py`

Then open http://localhost:8000 to use the Web UI.


A local Model Context Protocol (MCP) tool server exposing WhatsApp data (messages, chats, contacts) plus a lightweight self‑hosted Web UI (pure HTML/JS) and a JSON API (FastAPI).

## Features

- MCP tool server (`main.py`) that exposes:
  - Search contacts
  - List chats
  - Get chat metadata
  - List messages (with optional context)
  - Send text, file, and audio (auto‐convert to Opus OGG if needed)
  - Download media
- FastAPI JSON API (`api_server.py`) providing structured endpoints
- Embedded minimal single‑page Web UI served at `/`
- SQLite message store read‑only access (no migrations required)
- Clean dataclass → dict serialization for API/tools

## Project Layout (Flat Module Layout)

```
whatsapp-mcp-server/
  main.py              # MCP server entry (stdio transport)
  api_server.py        # FastAPI app (run a local web server)
  whatsapp.py          # Core data + WhatsApp bridge interaction logic
  audio.py             # Audio conversion helpers (ffmpeg required for non .ogg)
  pyproject.toml       # Build metadata & dependencies
```

This uses a flat layout with `py_modules` specified in `pyproject.toml` to avoid setuptools auto-discovery errors.

## Prerequisites

- Python 3.11+
- Local WhatsApp bridge/API running at `http://localhost:8080/api`
- SQLite message database located at: `../whatsapp-bridge/store/messages.db` relative to this directory
- (Optional) `ffmpeg` installed on PATH for audio transcoding

## Installation

From inside the `whatsapp-mcp-server` directory (or project root if you prefer):

```bash
# Using uv (recommended if available)
uv pip install -e .

# Or with pip
pip install -e .
```

If you encounter network failures resolving dependencies (e.g. `uvicorn`), retry or configure a PyPI mirror (or supply an alternate index URL).

## Database Initialization

The application expects a SQLite database at:  
`whatsapp-bridge/store/messages.db`

Create the schema (and optional demo data) using the provided script:

```bash
cd whatsapp-mcp-server/whatsapp-bridge/store
python initialize_messages_db.py --seed
```

This will create `messages.db` and insert a small sample of chats and messages so the Web UI immediately shows data.

To completely reset and reseed:

```bash
python initialize_messages_db.py --reset --seed
```

For a blank schema (no demo messages):

```bash
python initialize_messages_db.py
```

You can safely re-run the script; it is idempotent unless `--reset` is specified.

## Running the FastAPI Web API + UI

```bash
python api_server.py
```

Then open:  
http://127.0.0.1:8000

Endpoints (non-exhaustive):
- `GET /api/health`
- `GET /api/chats`
- `GET /api/chats/{jid}`
- `GET /api/chats/{jid}/messages`
- `GET /api/messages`
- `GET /api/contacts?q=...`
- `POST /api/messages/send`
- `POST /api/messages/send-file`
- `POST /api/messages/send-audio`
- `POST /api/media/download`

## Running the MCP Tool Server

If using an MCP-capable client:

```bash
python main.py
```

This uses stdio transport. Configure your MCP-aware client to launch it.

## Sending Messages

Text:
```bash
curl -X POST http://localhost:8000/api/messages/send \
  -H 'Content-Type: application/json' \
  -d '{"recipient":"123456789@s.whatsapp.net","message":"Hello!"}'
```

File (expects file already saved locally – current endpoint uses a path, not multipart upload):
```bash
curl -X POST http://localhost:8000/api/messages/send-file \
  -H 'Content-Type: application/json' \
  -d '{"recipient":"123456789@s.whatsapp.net","media_path":"/absolute/path/to/image.jpg"}'
```

## Audio Conversion

If you send an audio file that is not `.ogg`:
- `audio.convert_to_opus_ogg_temp()` creates a temporary converted file.
- Requires `ffmpeg` (`brew install ffmpeg` on macOS).

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: fastapi` | Dependencies not installed | Re-run `pip install -e .` |
| Setuptools error: multiple top-level modules | Flat layout without explicit modules list | We specify `py_modules` in `pyproject.toml` (already fixed) |
| `ffmpeg` errors on audio send | Missing ffmpeg | Install ffmpeg |
| Empty chat list | DB path wrong or bridge not producing data | Verify `MESSAGES_DB_PATH` and file permissions |
| `requests` failures | Bridge not running | Start the WhatsApp bridge at `localhost:8080` |

## Extending

Recommended next steps (pick any):
1. Add WebSocket (or SSE) for real-time updates.
2. Replace simple UI with React/Vite or SvelteKit.
3. Implement multipart upload for media instead of path-based send.
4. Add authentication (API key / token).
5. Introduce message cursor-based pagination instead of page/limit.
6. Wrap as a desktop app (Electron or Tauri).

## Security Notes

- No authentication: keep this local-only.
- Do not expose `api_server.py` to the public internet without adding auth + TLS.
- File paths for sending media are trusted input—sanitize if exposing beyond localhost.

## Development Tips

Format / lint manually if desired (project does not yet include black/ruff):
```bash
pip install ruff black
ruff check .
black .
```

## License

Internal / Unspecified (add one if you intend to distribute).

## Disclaimer

This project assumes you have a legal right to interact with the underlying WhatsApp data source. Use responsibly and comply with platform terms.

---

Feel free to request enhancements and we can evolve this scaffold further.