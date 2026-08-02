# Security & privacy

## Privacy & telemetry {#privacy--telemetry}

**No phone home.** `/avo.stats` and phase telemetry read **local disk only**. No analytics backend. No accounts. No usage upload.

**What stays on your machine**

| Location | What | In git? |
| -------- | ---- | ------- |
| `.avo/state.json` | Rolling telemetry + session history + aggregate totals | No (gitignored) |
| `.avo/sessions/<id>/` | Pre-inventory snapshot, session meta, optional phase log | No (gitignored) |
| `<rawDir>/avo.wrap.*` | Per-video wrap reports (draft + final) on your footage volume | No (external media) |

**What stats modules do not do**

- No network I/O in `src/avo/stats.py`, `src/avo/session.py`, `src/avo/project_inventory.py`, or `src/avo/wrap.py`
- No secrets, API keys, or `.env` contents in session records or wrap JSON
- No provider rollup files under tracked `providers/` paths in v1

**Install-time network is separate**

Setup may use network for things you explicitly run: `git clone`, `git pull`, model downloads, npm/pip installs, agent skill registries. That is **not** runtime stats telemetry. See [`docs/install/README.md`](docs/install/README.md) and [`docs/repo-layout.md`](docs/repo-layout.md).

**Path metadata**

Session records and wrap files may store **absolute paths** to your footage folders. That is local audit metadata on your disk — not transmitted.

**ai-memory**

Optional learndown may use [ai-memory](https://github.com/akitaonrails/ai-memory) under its own policy. AVO stats work with ai-memory absent.

**Trust check**

Run `/avo.stats` offline. Output comes from `.avo/state.json` on disk. Nothing leaves your machine for this feature.

---

## Reporting issues

Report security concerns via the repository's GitHub issue tracker. Do not paste secrets, `.env` contents, or private footage paths into public issues unless you intend to share them.
