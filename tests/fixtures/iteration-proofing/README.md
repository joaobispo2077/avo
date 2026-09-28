# Iteration-proofing fixtures

This directory defines small, deterministic, synthetic media used to
characterize AVO before iteration-aware proofing is added. No file contains
real footage, provider material, private paths, names, captions, or voices.

The manifest maps each proofing risk to generated media and machine-readable
expectations. Generate the complete set with:

```text
python tests/fixtures/iteration-proofing/build_fixtures.py <output-directory>
```

Use `--only` repeatedly to build selected scenarios. Generated binaries are
test outputs and are not tracked. `generated-manifest.json` records stable
SHA-256 and byte-size evidence.

Scenarios cover forbidden proof ancestry, speech joins, an isolated SFX
transient, a moving overlay, variable-frame-rate still-like material, hybrid
pacing, caption/privacy safe zones, and a sparse long-form Watch candidate.
The source and prior-proof files are deliberately byte-identical so tests can
prove that path/role ancestry cannot be replaced by byte comparison alone.

