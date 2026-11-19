# Offline semantic SFX qualification

Semantic search is optional. Descriptor search, the motion map and storyboard
need no ML packages or model files. An explicit semantic request uses paired
`audio_embed` and `text_embed` jobs with the same joint-space identity. It never
falls back to descriptor scores when the selected runtime is unavailable.

Provision model artifacts separately from AVO, using the official
[LAION CLAP model](https://huggingface.co/laion/clap-htsat-unfused) and a fixed
40-character repository revision. The tested model revision is
[8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a](https://huggingface.co/laion/clap-htsat-unfused/tree/8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a).
Keep the declared Apache-2.0 model notice and the notices shipped with each
runtime package. A source pin uses `kind: "artifact"`, an absolute `artifactPath`, and a
`manifestPath` inside that directory, with the manifest's exact SHA-256. Do not
point at a mutable online model or treat a named directory as readiness.

`avo.clap-manifest.schema.json` requires the model/processor/tokenizer files,
their digests, dimension, license notice, preprocessing and a runtime lock.
Every loader-discoverable JSON/text/model file must be listed. Configure a
separate Python executable and installed FFmpeg; the manifest pins both binary
digests and the actual package versions. The worker checks the exact Python
version and package versions before executing. It requires Torch 2.6 or newer
for restricted weight loading, static local Transformers classes and
`trust_remote_code=False`.

The selected runtime must declare `offline: true`, `allowDownload: false`,
`device: "cpu"` or `"cuda"`, and supported float32 computation. Worker network
entry points are blocked, and model/processor loading uses local files only.
Installation is separate from inference; a search never provisions tools or
weights. Saved global defaults and ordinary transcription jobs are independent.

For Windows x64 and CPython 3.11, the tested CPU runtime uses PyTorch
2.9.1+cpu, Transformers 4.57.6 and NumPy 2.2.6. Install into a separate virtual
environment using the [hashed wheel requirements](../config/sfx-clap-cpu-windows.requirements.txt).
The engine and Python distribution include this requirements file for explicit
provisioning. To provision a chosen interpreter, use
`uv pip install --require-hashes --only-binary=:all: -r <requirements> --python <interpreter>`.
Record the actual interpreter and FFmpeg fingerprints in the model manifest.

For repeatable local qualification, save the explicit model pin as a JSON file
outside tracked configuration. Select that file only for the integration test:

```powershell
$env:AVO_TEST_CLAP_PIN = '<absolute path to the qualification pin JSON>'
python -m pytest tests/integration/test_sfx_semantic_runtime.py -q
Remove-Item Env:AVO_TEST_CLAP_PIN
```

The test executes the actual isolated worker, checks finite normalized audio and
text vectors, performs semantic catalogue searches, verifies exact source/model
cache reuse and rejects changed source bytes. Its report records joint-space
and manifest identities. Ordinary CI skips this test when no local pin is
explicitly selected. Core Python dependencies remain unchanged.

A successful runtime test establishes execution and cache integrity. It does
not establish suitable sound choices, rights to production SFX, contextual
listening acceptance or final mix approval. Those require their own evidence.
