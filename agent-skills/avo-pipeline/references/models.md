# /avo.models reference

## Step/state mapping

**Durable state:** resolved catalog pins from config, `.avo/state.json`, provider, registry, and `avo.project.json`

**Workflow steps:** Resolve context → Inspect catalog pins → Optional preflight → Report

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing catalog, preflight failure, a required human decision, or verified inspect/preflight output

**Valid next commands:** /avo.help, /avo.transcribe, /avo.watch

Inspect catalog ids and resolved physical sources. Owning helper: `src/avo/models_cli.py` plus `src/avo/model_sources.py`.

v1 is **inspect/preflight**. Pins are JSON edits at project, provider, or install/state scope. Do not add `models_cli set`, spawn llama-server, or store `apiKey` values (env **names** only via `apiKeyEnv`).

```bash
python -m avo.models_cli show --json
python -m avo.models_cli alternatives understand
python -m avo.models_cli preflight
```

Show JSON includes `activeModels` (labels) and `resolvedModelSources` (id, winning scopes, artifact paths, redacted endpoint, device/compute, reuse).

More-specific wins: catalog → global → state → provider → registry → video-state → project → invocation. Same-file `models.transcribe` beats `transcription.model`. An id-only higher scope clears inherited source/runtime so a `medium` id cannot keep a `large-v3` path.

See [`docs/model-transparency.md`](../../../docs/model-transparency.md).
