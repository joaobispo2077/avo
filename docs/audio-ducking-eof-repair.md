# Deterministic ducking at source EOF

The audio layer compiler pads both compressor inputs with silence and trims
the result at the ducked layer's absolute region end (48 kHz samples). The
dialogue mix branch is not padded or attenuated by this change. Ducked layers
without a positive finite end cannot be rendered.

Previously, unequal physical source lengths could terminate sidechain output
early. A regression fixture with 100 ms dialogue and 350 ms music returned
only 100 ms. The test now checks complete sample output, delayed music, silence
after music ends and repeated executions. Padding is bounded downstream; it
must never produce an unbounded output.

This is separate from breath reduction. Frozen breath materialization still
reconstructs the untreated canonical mix and subtracts only the dialogue delta.
It must not process an old proof or change music ducking in response to reduced
breaths. A restored tail can differ from an earlier buggy render; it requires
an explicit review record rather than a claim of historical bit identity.

Verification:

```text
python -m pytest tests/test_timeline_audio_compiler.py tests/integration/test_ducking_eof.py tests/integration/test_breath_control_runtime.py
```

The external footage project owns its render comparisons and source receipts.
No per-video paths or assets are embedded in the reusable compiler.
