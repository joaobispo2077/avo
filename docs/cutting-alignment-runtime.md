# Optional cutting alignment runtime

Cutting uses the existing faster-whisper transcription and bundled CPU Silero
VAD. Character alignment additionally uses WhisperX **3.8.6**, only inside an
explicitly provisioned, isolated environment. It does not install into AVO's
core environment or enable cutting automatically.

## Reproducible provisioning

`requirements/cutting-alignment.txt` contains all 102 distributions selected by
pip's resolver on 2026-10-10, pinned with distribution SHA-256 hashes for Windows
amd64 and CPython 3.11. It was generated with `--dry-run --ignore-installed
--only-binary=:all:`; no packages or models were installed. This is a dependency
resolution result, not evidence that alignment inference has passed validation.
Other Python versions, platforms or accelerator builds need their own resolved
and tested lock. Do not reuse these platform-specific hashes silently.

After the user explicitly chooses to provision the optional runtime:

```powershell
py -3.11 -m venv <chosen-runtime-directory>
<chosen-runtime-directory>/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: -r requirements/cutting-alignment.txt
```

Keep the runtime outside AVO's core `.venv`. The dependencies include PyTorch,
torchaudio and packages required by WhisperX distribution metadata even though
AVO does not invoke its diarization or transcription pipelines. Inference must
select CPU explicitly; package presence does not authorize GPU usage.

## Explicit local models and resources

Provision complete model snapshots, including tokenizer/configuration files,
to user-selected directories. Record the repository revision and SHA-256 of all
required files; a floating model name is not a reproducible identity.

| Language | Model repository | Declared model license |
| --- | --- | --- |
| English | `facebook/wav2vec2-base-960h` | Apache-2.0 |
| Portuguese | `jonatasgrosman/wav2vec2-large-xlsr-53-portuguese` | Apache-2.0 |

WhisperX is BSD-2-Clause. Preserve package/model notices and assess the complete
dependency license inventory when distributing a runtime. The model's language
support is not proof that AVO's cutting policy passed PT-BR/English evaluation.

Explicit provisioning must also obtain NLTK `punkt_tab` Portuguese and English
resources. WhisperX 3.8.6 calls `nltk.download` when these are absent, so **validate
resources before invoking alignment** and reject an incomplete installation.
An optional installation must never become an implicit network download.

Configure these explicitly provisioned paths in the external project's cutting
settings. Replace the illustrative placeholders with actual paths, pinned
revisions and SHA-256 values; the example is not a downloadable model manifest.

```json
{
  "cutting": {
    "enabled": true,
    "family": "analysis-review",
    "intensity": "balanced",
    "language": "pt-BR",
    "runtimeRefs": {
      "alignment": {
        "python": "<runtime>/Scripts/python.exe",
        "nltkData": "<explicit-nltk-directory>",
        "models": {
          "pt": {
            "path": "<local-portuguese-model-snapshot>",
            "revision": "<pinned-revision>",
            "files": {"config.json": "<sha256>", "<weight-file>": "<sha256>"}
          },
          "en": {
            "path": "<local-english-model-snapshot>",
            "revision": "<pinned-revision>",
            "files": {"config.json": "<sha256>", "<weight-file>": "<sha256>"}
          }
        },
        "timeoutSeconds": 120
      }
    }
  }
}
```

Include **every required tokenizer, configuration and weight file** in each
manifest. `models.transcribe` continues to use AVO's existing prepared local
ASR model configuration; `models.understand` and the existing Watch policy own
visual/context inference. Changing configured model bytes, Punkt resources,
policy or generator code invalidates affected proposals. Missing measurements
remain unknown. Runtime packages and real PT/EN inference are not validated by
the generated-signal tests in the core suite.

## Worker contract

The alignment adapter must use a bounded CPU worker with local PCM input and
versioned output, one request at a time. Use absolute model directories with
`load_align_model(..., device="cpu", model_cache_only=True)`, then
`align(..., interpolate_method="ignore", return_char_alignments=True)`.
Enforce offline model/cache flags, local NLTK paths and a network-disabled worker.
Preflight the runtime, local artifacts and resource hashes before analysis.

Do not use default torchaudio pipeline names, which can fetch weights. Do not
invoke WhisperX transcription, speaker diarization or TorchAudio forced-alignment
APIs. Qwen visual analysis remains separately serialized under the existing
7 GB VRAM ceiling; still images cannot certify speech integrity.

Missing, interpolated, wildcard and unsupported-character alignments remain
unknown evidence and cannot anchor automatic cuts. Model/implementation changes
invalidate affected evidence. Failed decoding or alignment is never silence.

## Validation before declaring availability

Check offline startup, missing-model/Punkt rejection, selected-stream PCM routing,
PT-BR/English character alignment, unsupported digits/names, CPU resource use,
timeout handling and model identity. Record measured values; absent measurements
remain null. Actual acoustic and rendered boundary checks remain mandatory even
when character alignment succeeds.

Sources: [WhisperX pinned API](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py),
[release metadata](https://pypi.org/project/whisperx/3.8.6/),
[English model card](https://huggingface.co/facebook/wav2vec2-base-960h),
[Portuguese model card](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-portuguese).
