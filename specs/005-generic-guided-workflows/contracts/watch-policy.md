# Contract: Configurable Watch Execution and Review Policy

## Persistent configuration

```json
{
  "watch": {
    "whisperModel": "inherit",
    "device": "auto",
    "maxFrames": 18,
    "repairMaxFrames": 8,
    "analysisAttempts": 2,
    "toolAttempts": 3,
    "workingDirectory": null,
    "format": null,
    "language": null,
    "acceptanceCriteria": [],
    "riskNotes": []
  }
}
```

Valid locations are `config/avo.config.json`, `routingOverrides.watch` in the provider manifest, `defaults.watch` in the video registry, and `watch` in `avo.project.json`. Precedence is global → provider → registry → project → invocation. Arrays replace less-specific arrays. Every effective field records its winning source.

Validation:

- `whisperModel`: `inherit` or a supported model/catalog ID.
- `device`: `auto`, `cpu`, `cuda`, or `cuda:N`.
- `maxFrames` and `repairMaxFrames`: `1..64`; repair must not exceed primary.
- `analysisAttempts` and `toolAttempts`: `1..3`.
- Relative `workingDirectory`: resolve against `rawDir`; omitted uses candidate directory.
- Missing format/language/context: omit from prompt; never guess.

Required exact-candidate Watch gates cannot be disabled.

## Invocation controls

`review run` and the read-only `review policy` command support:

```text
--watch-whisper-model VALUE
--watch-device auto|cpu|cuda|cuda:N
--watch-max-frames N
--watch-repair-max-frames N
--watch-analysis-attempts N
--watch-tool-attempts N
--watch-work-dir PATH
--watch-format VALUE
--watch-language VALUE
--watch-criterion VALUE       # repeatable
--watch-risk-note VALUE       # repeatable
```

`review policy` validates and emits `effective`, `sources`, and `policyHash` without invoking Watch. Invalid options stop before indexing or transcription.

## Execution behavior

- `whisperModel=inherit` uses the resolved AVO transcription model.
- Only explicit `device=cpu` sets `CUDA_VISIBLE_DEVICES=-1`.
- `auto` preserves the environment; `cuda`/`cuda:N` apply only their documented device selection.
- Working directory and artifact directory are separate: raw Watch execution defaults to candidate directory; evidence remains under the canonical review directory.
- Tool/acquisition failures may retry the complete operation up to `toolAttempts`.
- Malformed structured output may run repair prompts up to `analysisAttempts` against the same indexed candidate.

## Prompt inputs

Prompt construction uses only:

1. checkpoint and required scope;
2. required windows with timestamps and reasons;
3. declared format and language;
4. checkpoint/QC plus configured acceptance criteria;
5. declared risk notes;
6. exact candidate transcript reference and validated names/terms;
7. the structured-output contract.

No provider/topic identity, project subject, assumed language/format, machine path, or parseable example JSON object is embedded. The requested result is one object with valid `status`, numeric confidence, and a list of finding objects.

## Parsing and fail-closed outcomes

- Select the last complete schema-valid analysis object; ignore echoed window/context objects.
- Valid `needs-human-judgment`: `outcomeKind=uncertainty`, no automatic repair.
- Recognized refusal: normalized human-judgment result with `outcomeKind=refusal`, no automatic repair.
- Exhausted malformed output: non-retryable `WATCH_MALFORMED`, blocked.
- Exhausted process/acquisition failure: `WATCH_UNAVAILABLE`, blocked.
- Missing required-window/full coverage: non-retryable `WATCH_SCOPE_INSUFFICIENT`, blocked.
- Preserve tolerant UTF-8 decoding and raw output from every attempt.

## Evidence

Watch evidence adds:

```json
{
  "policy": {
    "effective": {},
    "sources": {},
    "fingerprint": "<sha256>"
  },
  "reviewContext": {},
  "promptSha256": "<sha256>",
  "outcomeKind": "content",
  "attempts": []
}
```

Actual tool/model identity remains separate from requested policy. Candidate-bound `review.json` retains policy hash and outcome kind so a policy change invalidates stale evidence and uncertainty remains distinguishable from content failure.
