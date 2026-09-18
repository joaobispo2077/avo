# /avo.models Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Resolve context → Inspect catalog pins → Optional preflight → Report
**Step state source:** `avo.config.json`, `.avo/state.json`, provider/project manifests
**Stopping conditions:** Missing catalog, preflight failure, or a required human decision
**Valid next commands:** /avo.help, /avo.transcribe, /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Inspect which catalog id, physical source, and runtime would run. v1 is read-only.

**Skill:** [`agent-skills/avo-pipeline/references/models.md`](../../agent-skills/avo-pipeline/references/models.md)

---

## Usage

```
/avo.models
/avo.models --json
/avo.models alternatives transcribe
/avo.models preflight
```

---

## Role

Inspect/preflight only. Do not spawn llama-server, download weights, or write secrets.
There is no `models_cli set`. To change a pin, edit JSON at the scope the user names.

---

## Instructions

1. Run `python -m avo.models_cli show` (add `--json` when the user wants machine output).
2. Show `activeModels` labels **and** `resolvedModelSources` (id, scopes, paths, redacted endpoint, device/compute, reuse).
3. `alternatives <job>` lists lighter/heavier catalog rows. Hardware advisory must not swap files.
4. `preflight` fail-closes on missing artifacts, incomplete Hub snapshots, unreachable endpoints, served-name mismatch, unsupported explicit compute, disallowed download, or missing `apiKeyEnv`.
5. To change a pin, edit the more-specific file the user names:
   - this video → `<rawDir>/avo.project.json` `models.*` (or legacy `transcription.model`)
   - this channel → `providers/<slug>/avo.provider.json` `models.*`
   - this machine → `.avo/state.json` or `config/avo.config.json`
   Apply that edit only after the user names the scope.

## CLI equivalent

```bash
python -m avo.models_cli show
python -m avo.models_cli show --json
python -m avo.models_cli alternatives transcribe
python -m avo.models_cli disclosure
python -m avo.models_cli preflight
python -m avo.models_cli preflight understand --json
```

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.
