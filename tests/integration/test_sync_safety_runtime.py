from __future__ import annotations

from pathlib import Path

import pytest

from avo.adapters.media.sync_materializer import (
    SyncMaterializationError,
    SyncMaterializer,
)


def test_materializer_rejects_non_raw_kind_and_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "raw.bin"
    path.write_bytes(b"raw")
    materializer = SyncMaterializer()
    with pytest.raises(SyncMaterializationError, match="raw"):
        materializer.validate_inputs(
            path, path, picture_kind="corrected-delivery", audio_kind="raw"
        )
    with pytest.raises(SyncMaterializationError, match="fingerprint"):
        materializer.validate_inputs(
            path, path, expected_picture_sha256="0" * 64, expected_audio_sha256="0" * 64
        )


def test_negative_offset_filter_trims_audio() -> None:
    plan = SyncMaterializer().compile_audio_filter(
        {
            "kind": "constant-offset",
            "offsetTicks": -128,
            "timebase": {"num": 1, "den": 1000},
        }
    )
    assert "atrim=start=0.128" in plan.filter_complex
    assert plan.output_label == "synca"
