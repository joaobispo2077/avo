# Claude Code — wire local `avo.mcp`

Requires `pip install -e ".[mcp]"` (or `pip install "avo[mcp]"`) first. Phase-1 is **stdio** only — no `url` / HTTP server.

## Add (installed env)

```bash
claude mcp add avo -- python -m avo.mcp
```

Prefer an absolute path to the venv Python when the shell that launches Claude Code is not the project env:

```bash
claude mcp add avo -- /absolute/path/to/venv/bin/python -m avo.mcp
```

## Editable checkout (`src` layout)

```bash
claude mcp add avo --env PYTHONPATH=src -- python -m avo.mcp
```

Windows PowerShell (same idea):

```powershell
claude mcp add avo --env PYTHONPATH=src -- python -m avo.mcp
```

## Alternate: `uv run`

From the AVO repo root (editable + frozen lockfile):

```bash
claude mcp add avo --env PYTHONPATH=src -- uv run --frozen python -m avo.mcp
```

## Cursor JSON twin

Copy [`cursor-mcp.example.json`](cursor-mcp.example.json) into `.cursor/mcp.json` (merge under `mcpServers` if the file already exists). That template uses `uv run`; after a normal install, switch to `"command": "python"` and `"args": ["-m", "avo.mcp"]` and drop `PYTHONPATH` unless you need the editable `src` layout.

## Smoke

After the harness shows `avo` connected: call `avo_health`, then `avo_list_capabilities`. Full checklist: [`docs/avo-mcp.md`](../../avo-mcp.md).

**Not** an editor/NLE MCP — see [`docs/why-not-editor-mcp.md`](../../why-not-editor-mcp.md). Distinct from HTTP [`ai-memory` templates](../ai-memory/cursor-mcp.example.json).
