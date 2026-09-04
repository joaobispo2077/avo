from __future__ import annotations

import pytest

from avo.adapters.qc.source_fidelity import (
    media_from_probe,
    source_fidelity_evidence,
)
from avo.delivery_fidelity import (
    DELIVERY_FIDELITY_CHECKPOINTS,
    DeliveryFidelityPolicyError,
    resolve_delivery_fidelity_policy,
)
from avo.timeline.contracts import content_hash
from avo.timeline.review import CHECKPOINT_POLICIES

HASH_A = "a" * 64
HASH_B = "b" * 64


def _policy(*, allowed: list[str] | None = None, encoding: dict | None = None) -> dict:
    return resolve_delivery_fidelity_policy(
        profile_id="fixture-1080p",
        render_contract={
            "width": 1920,
            "height": 1080,
            "displayAspectRatio": "16:9",
            "frameRate": {"num": 30, "den": 1, "tolerance": 0.001},
            "durationSeconds": 10.0,
            "durationToleranceSec": 0.05,
            "allowedTransformations": allowed or ["trim", "concat", "encode"],
            "encodingRules": encoding or {},
        },
        setting_sources={"profileId": "project"},
    )


def _materialization(
    *,
    policy: dict | None = None,
    media_class: str = "camera-original",
    edge_operation: str = "encode",
    approval_reference: str | None = None,
    overlay: dict | None = None,
) -> dict:
    resolved_policy = policy or _policy()
    nodes = [
        {
            "nodeId": "base-001",
            "kind": "source",
            "role": "base",
            "mediaClass": media_class,
            "locator": "raw/master.mov",
            "sha256": HASH_A,
            "pictureCarrying": True,
            "media": {"width": 1920, "height": 1080},
        },
        {
            "nodeId": "output",
            "kind": "output",
            "role": "output",
            "mediaClass": "approved-master",
            "locator": "delivery/master.mp4",
            "sha256": HASH_B,
            "pictureCarrying": True,
            "media": {"width": 1920, "height": 1080},
        },
    ]
    edges = [
        {
            "from": "base-001",
            "to": "output",
            "operation": edge_operation,
            "parameters": {},
            **({"approvalReference": approval_reference} if approval_reference else {}),
        }
    ]
    if overlay:
        nodes.insert(1, overlay)
        edges.insert(
            0,
            {
                "from": overlay["nodeId"],
                "to": "output",
                "operation": "composite",
                "parameters": {},
            },
        )
    lineage_body = {"nodes": nodes, "edges": edges, "rootIds": ["output"]}
    lineage = {
        **lineage_body,
        "pictureLineageHash": content_hash(lineage_body),
    }
    body = {
        "schemaVersion": "1.1.0",
        "kind": "assembly",
        "canonicalInputLock": {
            "cmapRevisionHash": "c" * 64,
            "syncRevisionHash": "d" * 64,
            "bmapRevisionHash": "e" * 64,
            "tracksRevisionHash": "f" * 64,
            "rawFingerprints": {"raw/master.mov": HASH_A},
        },
        "projectionHash": "1" * 64,
        "renderProfile": "delivery",
        "renderContract": resolved_policy["renderContract"],
        "renderContractHash": content_hash(resolved_policy["renderContract"]),
        "pictureLineage": lineage,
        "pictureLineageHash": lineage["pictureLineageHash"],
        "deliveryFidelityPolicy": resolved_policy,
        "deliveryFidelityPolicyHash": resolved_policy["policyHash"],
        "output": {"locator": "delivery/master.mp4", "sha256": HASH_B},
        "producer": {"tool": "fixture", "version": "1"},
    }
    return {**body, "materializationHash": content_hash(body)}


def _candidate(**overrides) -> dict:
    return {
        "locator": "delivery/master.mp4",
        "sha256": HASH_B,
        "width": 1920,
        "height": 1080,
        "frameRate": 30.0,
        "durationSeconds": 10.0,
        "bitRate": 10_000_000,
        "codec": "h264",
        **overrides,
    }


def _rehash(materialization: dict) -> None:
    lineage_body = {
        key: value
        for key, value in materialization["pictureLineage"].items()
        if key != "pictureLineageHash"
    }
    lineage_hash = content_hash(lineage_body)
    materialization["pictureLineage"]["pictureLineageHash"] = lineage_hash
    materialization["pictureLineageHash"] = lineage_hash
    materialization["materializationHash"] = content_hash(
        {
            key: value
            for key, value in materialization.items()
            if key != "materializationHash"
        }
    )


def test_source_fidelity_is_required_only_for_master_checkpoints():
    assert DELIVERY_FIDELITY_CHECKPOINTS == frozenset({"pre-master", "deliver"})
    for name, policy in CHECKPOINT_POLICIES.items():
        assert ("source-fidelity" in policy["required"]) == (
            name in DELIVERY_FIDELITY_CHECKPOINTS
        )


def test_profile_validation_and_hash_are_deterministic():
    assert _policy()["policyHash"] == _policy()["policyHash"]
    with pytest.raises(DeliveryFidelityPolicyError, match="width"):
        resolve_delivery_fidelity_policy(
            profile_id="fixture",
            render_contract={
                "width": 0,
                "height": 1080,
                "frameRate": {"num": 30, "den": 1},
                "allowedTransformations": [],
            },
        )


def test_native_and_declared_scale_down_follow_profile_not_source_dimensions():
    assert (
        source_fidelity_evidence(
            checkpoint="deliver",
            candidate=_candidate(),
            materialization=_materialization(),
        )["disposition"]
        == "pass"
    )
    scaled = _materialization(
        policy=_policy(allowed=["scale-down"]), edge_operation="scale-down"
    )
    scaled["pictureLineage"]["nodes"][0]["media"] = {
        "width": 3840,
        "height": 2160,
    }
    _rehash(scaled)
    assert (
        source_fidelity_evidence(
            checkpoint="deliver", candidate=_candidate(), materialization=scaled
        )["disposition"]
        == "pass"
    )


def test_undeclared_operation_and_unapproved_reframe_fail():
    undeclared = source_fidelity_evidence(
        checkpoint="pre-master",
        candidate=_candidate(),
        materialization=_materialization(edge_operation="scale-down"),
    )
    assert "transformation-not-allowed" in {
        finding["id"] for finding in undeclared["findings"]
    }
    reframed = source_fidelity_evidence(
        checkpoint="pre-master",
        candidate=_candidate(),
        materialization=_materialization(
            policy=_policy(allowed=["reframe"]), edge_operation="reframe"
        ),
    )
    assert "transformation-approval-missing" in {
        finding["id"] for finding in reframed["findings"]
    }

    approved = source_fidelity_evidence(
        checkpoint="pre-master",
        candidate=_candidate(),
        materialization=_materialization(
            policy=_policy(allowed=["reframe"]),
            edge_operation="reframe",
            approval_reference="approval://picture-lock/reframe-001",
        ),
    )
    assert approved["disposition"] == "pass"


def test_prohibited_base_reports_exact_node_but_lower_resolution_overlay_is_allowed():
    prohibited = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(),
        materialization=_materialization(media_class="proof"),
    )
    assert prohibited["disposition"] == "fail"
    assert prohibited["details"]["offendingNodeIds"] == ["base-001"]
    overlay = {
        "nodeId": "overlay-001",
        "kind": "source",
        "role": "overlay",
        "mediaClass": "proof",
        "locator": "overlay.png",
        "sha256": "9" * 64,
        "pictureCarrying": True,
        "media": {"width": 640, "height": 360},
    }
    permitted = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(),
        materialization=_materialization(
            policy=_policy(allowed=["encode", "composite"]), overlay=overlay
        ),
    )
    assert permitted["disposition"] == "pass"


def test_role_policy_can_constrain_overlay_class_and_resolution():
    overlay = {
        "nodeId": "overlay-001",
        "kind": "source",
        "role": "overlay",
        "mediaClass": "preview",
        "locator": "overlay.png",
        "sha256": "9" * 64,
        "pictureCarrying": True,
        "media": {"width": 640, "height": 360},
    }
    policy = resolve_delivery_fidelity_policy(
        profile_id="role-aware",
        render_contract={
            **_policy()["renderContract"],
            "allowedTransformations": ["encode", "composite"],
        },
        role_rules={
            "overlay": {
                "allowedMediaClasses": ["camera-original", "graphic"],
                "minimumWidth": 1280,
            }
        },
    )
    result = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(),
        materialization=_materialization(policy=policy, overlay=overlay),
    )
    assert result["details"]["offendingNodeIds"] == ["overlay-001"]
    assert {finding["id"] for finding in result["findings"]} == {
        "prohibited-picture-ancestor",
        "picture-role-resolution-below-profile",
    }


def test_bitrate_rule_is_codec_scoped_and_never_global():
    policy = _policy(encoding={"h264": {"minimumBitRate": 12_000_000}})
    h264 = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(codec="h264", bitRate=8_000_000),
        materialization=_materialization(policy=policy),
    )
    assert "codec-bitrate-below-profile" in {
        finding["id"] for finding in h264["findings"]
    }
    hevc = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(codec="hevc", bitRate=8_000_000),
        materialization=_materialization(policy=policy),
    )
    assert hevc["disposition"] == "pass"


def test_missing_stale_and_mismatched_prerequisites_are_blocked():
    missing = source_fidelity_evidence(
        checkpoint="deliver", candidate=_candidate(), materialization=None
    )
    assert missing["status"] == "error"
    assert missing["disposition"] == "blocked"
    stale = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(),
        materialization=_materialization(),
        current_revision_hashes={"cmapRevisionHash": "0" * 64},
    )
    assert stale["disposition"] == "blocked"
    mismatch = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(sha256="0" * 64),
        materialization=_materialization(),
    )
    assert mismatch["disposition"] == "blocked"

    incomplete = _materialization()
    incomplete["pictureLineage"]["rootIds"] = ["missing-output"]
    _rehash(incomplete)
    result = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(),
        materialization=incomplete,
    )
    assert result["disposition"] == "blocked"
    assert result["findings"][0]["id"] == "picture-lineage-incomplete"


def test_changed_policy_without_rebinding_is_blocked():
    materialization = _materialization()
    materialization["deliveryFidelityPolicy"]["profileId"] = "changed"
    materialization["materializationHash"] = content_hash(
        {
            key: value
            for key, value in materialization.items()
            if key != "materializationHash"
        }
    )
    result = source_fidelity_evidence(
        checkpoint="deliver",
        candidate=_candidate(),
        materialization=materialization,
    )
    assert result["disposition"] == "blocked"
    assert result["findings"][0]["id"] == "delivery-policy-stale"


def test_media_from_probe_is_assumption_free_and_preserves_frame_rate():
    media = media_from_probe(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "avg_frame_rate": "30000/1001",
                }
            ],
            "format": {"duration": "10.0", "size": "12500000"},
        },
        locator="raw.mp4",
        sha256=HASH_A,
    )
    assert media["bitRate"] == 10_000_000
    assert media["codec"] == "hevc"
    assert media["frameRate"] == pytest.approx(30000 / 1001)
    assert media["sha256"] == HASH_A


def test_before_pre_master_is_not_applicable():
    result = source_fidelity_evidence(
        checkpoint="cut-proof",
        candidate=_candidate(),
        materialization=None,
    )
    assert result["disposition"] == "not-applicable"
