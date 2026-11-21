"""Native ArtCraft declarations cannot acquire proof authority by relabeling."""

from types import SimpleNamespace

import pytest

from avo.artcraft import seal_record
from avo.timeline.contracts import file_fingerprint
from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService
from avo.timeline.media_admission import MediaAdmissionError, require_media_admission
from tests.artcraft_fixtures import picture_output


@pytest.fixture
def asset(tmp_path):
    source = tmp_path / "native.anicraft"
    source.write_bytes(b"synthetic authorial document")
    output = tmp_path / "native-overlay.mov"
    output.write_bytes(b"synthetic alias of a candidate output")
    source_fingerprint = file_fingerprint(source)
    fingerprint = file_fingerprint(output)
    receipt = seal_record(
        "receipt",
        {
            "version": 1,
            "artifactState": "admitted",
            "app": "anicraft",
            "requestHash": "a" * 64,
            "packageHash": "b" * 64,
            "parameterHash": "c" * 64,
            "recipeHash": "d" * 64,
            "environmentHash": "e" * 64,
            "inputs": [source_fingerprint],
            "output": picture_output(format="quicktime"),
            "observed": [fingerprint],
            "rebuildEvidenceHash": "f" * 64,
            "bindingHash": "a" * 64,
        },
    )
    record = {
        "assetId": "artcraft-speaker-label",
        "role": "overlay",
        "generator": {
            "adapterId": "artcraft.anicraft",
            "version": "0.0-test",
            "executableSha256": "e" * 64,
            "sourceSha256": "b" * 64,
        },
        "parameters": {"artcraft": receipt},
        "inputs": [
            {
                "artifactId": "native-document",
                "fingerprint": source_fingerprint,
                "ancestryRole": "dependency",
            }
        ],
        "sourceFree": False,
        "environment": {"platform": "windows", "dependencies": {}},
        "output": fingerprint,
        "reproducibility": "verified",
        "approvalReference": None,
    }
    return GeneratedAssetService(
        SimpleNamespace(timeline_dir=tmp_path / "edit" / "timeline")
    ), record


@pytest.mark.parametrize(
    "adapter_id, include_receipt",
    [
        ("artcraft.anicraft", False),
        ("hyperframes", True),
        ("artcraft-effectcraft", False),
    ],
)
def test_receipt_is_inversely_bound_to_reserved_artcraft_adapter(
    asset, adapter_id, include_receipt
):
    service, record = asset
    record["generator"]["adapterId"] = adapter_id
    if not include_receipt:
        record["parameters"] = {}
    with pytest.raises(GeneratedAssetError, match="invalid.*generated asset"):
        service.register(record)
    assert not service.directory.exists()


@pytest.mark.parametrize("reproducibility", ["verified", "declared"])
def test_claimed_generated_artcraft_record_requires_independent_verification(
    asset, reproducibility
):
    service, record = asset
    record["reproducibility"] = reproducibility
    record["approvalReference"] = "caller-supplied-approval"
    with pytest.raises(GeneratedAssetError, match="ArtCraft.*observations"):
        service.register(record)
    assert not service.directory.exists()


def test_recursive_admission_requires_the_artcraft_verification_path(asset):
    _, record = asset
    contributor = {
        "nodeId": "speaker",
        "kind": "generated",
        "assetId": record["assetId"],
        **record["output"],
    }
    with pytest.raises(
        MediaAdmissionError, match="artcraft-freshness-verifier-required"
    ):
        require_media_admission(
            [contributor], generated_assets={record["assetId"]: record}
        )
