# BL-019 — Configurable model sources

**Status:** Implemented — see [`../active/configurable-model-sources/spec.md`](../active/configurable-model-sources/spec.md) (changelog/tag pending user approval)  
**Surface:** global config + provider manifest + external `avo.project.json` + model disclosure

## Problem

AVO can select logical model tiers, but operators may already have the same model in
different local caches, virtual environments, model servers, disks, or machines. AVO
must not silently download a duplicate or leave future reviewers unable to tell which
physical artifact and runtime served a job.

## Goal

Let an AVO user choose where each model comes from at three configuration levels, with
later scopes overriding earlier ones:

1. **Global** — defaults for this AVO installation.
2. **Provider** — defaults for one channel/brand.
3. **Project** — overrides for one external footage project.

The resolver must keep the logical catalog ID separate from its source and runtime.
Supported source shapes should include:

- Hugging Face/local cache directory or snapshot;
- direct model file plus companion files such as a vision `mmproj`;
- Python environment/package location where relevant;
- OpenAI-compatible local or remote endpoint and the model name exposed by it;
- device and compute settings such as CPU/CUDA, FP16, and offline-only behavior.

Secrets must be referenced through environment/credential mechanisms, not written into
provider or project manifests.

## Resolution and disclosure

Resolve `global → provider → project → one-run override`, validate required files before
the job starts, and fail closed when the configured source is unavailable. Do not
silently fall back to or download a different model while reporting the requested one.

Every run should record enough non-secret provenance to answer “which model did this
job actually use, and from where?” At minimum:

- job, logical catalog ID, and runtime-exposed model name;
- winning configuration scope;
- resolved cache/snapshot or artifact paths, including companion projector files;
- endpoint origin (with credentials/query secrets redacted);
- execution backend/device/compute type and offline/download policy;
- whether an existing artifact was reused or a download was explicitly approved.

Expose this through model inspection/disclosure and phase/delivery metadata so the
answer survives the chat that launched the run.

## Example scenarios

These neutral examples illustrate why source and runtime must be configurable; they
are not portable defaults:

- `faster-whisper/medium` loaded on CPU from a user-selected Hugging Face cache,
  using `faster-whisper` from the active Python environment.
- `faster-whisper/large-v3` loaded with CUDA/FP16 and
  `local_files_only=True` from a declared local snapshot.
- `bonsai-27b-gguf` served from a declared GGUF plus companion `mmproj`, exposed
  through a configured local OpenAI-compatible endpoint and served model name.

In all three cases AVO should reuse the declared local installation, make no duplicate
copy unless the user explicitly requests one, and disclose the resolved source.

## Acceptance criteria

- Global, provider, and project schemas accept the same model-source structure.
- Precedence is deterministic and inspectable; project overrides provider, which
  overrides global.
- Transcription supports catalog ID plus local cache/snapshot or explicit artifact path.
- Vision/understanding supports model file, projector file, endpoint, and served name.
- Paths may live outside the AVO repository and on any user-selected drive.
- Preflight distinguishes missing artifacts, unreachable endpoints, incompatible
  runtime settings, and disallowed downloads.
- Run and delivery metadata report the actual resolved source without leaking secrets.
- Existing model-tier-only configuration remains backward compatible.
- Tests cover precedence, Windows/POSIX paths, endpoint redaction, offline reuse, and
  fail-closed behavior.

