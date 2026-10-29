# Sequential GPU speech analysis

Cutting keeps its CPU defaults. Projects can explicitly select CUDA using the
existing `cutting.runtimeRefs` settings:

```json
{
  "transcription": { "device": "cuda", "computeType": "float16" },
  "alignment": { "device": "cuda" }
}
```

The alignment entry still requires its provisioned Python, model manifests and
Punkt resources. Install a compatible CUDA build of PyTorch and torchaudio in
that isolated environment explicitly. Missing CUDA fails the request; it does
not silently fall back to CPU or download packages.

Run speech analysis before visual review on memory-constrained GPUs. Do not
invoke Qwen review during GPU transcription/alignment. The acoustic adapter
serializes its calls, but does not manage or unload the operator's vision server.
Finish the speech process and confirm available GPU memory before visual review.

Transcription runtime choices bind cached model instances and evidence. Changing
device or compute type requires a new adapter and proposal. Existing reports
remain immutable historical evidence and must not be relabeled as GPU results.
Model hashes, offline alignment, word guards and human review remain required.

Retake discovery splits backward word-time jumps and does not group overlapping
attempts. This prevents nonmonotonic alignment from forming inverted source
intervals; it does not certify those word times or authorize a removal.
