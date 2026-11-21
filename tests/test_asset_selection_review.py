"""Asset options keep their original identity, intended background and rights state."""

import json
from pathlib import Path

import pytest
from PIL import Image

from avo.adapters.qc.asset_review import render_asset_sheet
from avo.cli import main
from avo.timeline.asset_review import inspect_asset_options
from avo.timeline.asset_selection import verify_application_assets
from avo.timeline.contracts import file_fingerprint
from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.motion_review import MotionReviewService
from tests.test_motion_authoring import item, propose, request, workspace

__all__ = ["workspace"]


def selection(root, name, option_id, **fields):
    facts = file_fingerprint(root / name)
    return {
        "optionId": option_id,
        "rootId": "approved-library",
        "relativePath": name,
        "sha256": facts["sha256"],
        "sizeBytes": facts["sizeBytes"],
        "kind": "logo",
        "subject": "Example Labs",
        "supplier": "creator",
        "rights": {"state": "owned", "evidence": "Creator-provided brand kit"},
        **fields,
    }


def test_numbering_flags_wrong_brand_failed_capture_and_rights(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGBA", (16, 16), (0, 128, 60, 0)).save(root / "logo.png")
    Image.new("RGB", (16, 16), "red").save(root / "other.png")
    Image.new("RGB", (16, 16), "blue").save(root / "restricted.png")
    (root / "broken.png").write_bytes(b"This is not an image")
    options = [
        selection(root, "other.png", "wrong-brand", subject="Other Labs"),
        selection(root, "broken.png", "failed-capture"),
        selection(root, "logo.png", "creator-option"),
        selection(
            root, "restricted.png", "unknown-rights", rights={"state": "unknown"}
        ),
    ]
    need = {"kind": "logo", "subject": "Example Labs", "supplier": "creator"}
    roots = [{"rootId": "approved-library", "locator": str(root)}]
    rows, png = inspect_asset_options(
        need, roots, options, "#abcdee", render_asset_sheet
    )
    assert [(row["number"], row["optionId"], row["state"]) for row in rows] == [
        (1, "creator-option", "ready-for-review"),
        (2, "failed-capture", "capture-failed"),
        (3, "unknown-rights", "rights-unverified"),
        (4, "wrong-brand", "subject-mismatch"),
    ]
    assert rows[0]["source"]["sha256"] == options[2]["sha256"]
    assert rows[0]["rights"]["evidence"] == "Creator-provided brand kit"
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(png)
    with Image.open(sheet) as image:
        assert image.getpixel((80, 40)) == (171, 205, 238)
    background = selection(root, "other.png", "background-image")
    context = {
        key: background[key]
        for key in ("rootId", "relativePath", "sha256", "sizeBytes")
    }
    _, over_photo = inspect_asset_options(
        need, roots, options, "#abcdee", render_asset_sheet, background_source=context
    )
    sheet.write_bytes(over_photo)
    with Image.open(sheet) as image:
        assert image.getpixel((80, 40)) == (255, 0, 0)
    reversed_result = inspect_asset_options(
        need, roots, list(reversed(options)), "#abcdee", render_asset_sheet
    )
    assert reversed_result == (rows, png)


def test_asset_path_cannot_bypass_the_selected_root(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fixture")
    option = selection(
        tmp_path,
        outside.name,
        "outside-option",
        relativePath=str(Path("..") / outside.name),
    )
    with pytest.raises(ValueError, match="escapes"):
        inspect_asset_options(
            {"kind": "logo", "subject": "Example Labs", "supplier": "creator"},
            [{"rootId": "approved-library", "locator": str(root)}],
            [option],
            "#ffffff",
            render_asset_sheet,
        )


def test_identical_assets_and_unavailable_existing_sources_remain_explicit(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    source = root / "mark.png"
    Image.new("RGB", (12, 12), "green").save(source)
    (root / "copy.png").write_bytes(source.read_bytes())
    (root / "moved.png").write_bytes(source.read_bytes())
    options = [
        selection(root, "mark.png", "first-mark"),
        selection(root, "copy.png", "same-mark"),
        selection(root, "moved.png", "moved-mark"),
        selection(root, "mark.png", "wrong-supplier", supplier="editor"),
    ]
    (root / "moved.png").unlink()
    rows, _ = inspect_asset_options(
        {"kind": "logo", "subject": "Example Labs", "supplier": "creator"},
        [{"rootId": "approved-library", "locator": str(root)}],
        options,
        "#ffffff",
        render_asset_sheet,
    )
    assert [row["state"] for row in rows] == [
        "ready-for-review",
        "source-unavailable",
        "duplicate",
        "supplier-mismatch",
    ]


def test_native_review_and_selection_keep_placeholders_pending(workspace, capsys):
    need = {
        "kind": "logo",
        "subject": "Example Labs",
        "supplier": "creator",
        "status": "missing",
    }
    proposed, _ = propose(workspace, items=[{**item(), "assets": [need]}])
    root = workspace.raw_dir / "selected-library"
    root.mkdir()
    Image.new("RGB", (16, 16), "green").save(root / "logo.png")
    Image.new("RGB", (16, 16), "blue").save(root / "different.png")
    proposal_hash = proposed["proposalRef"]["sha256"]
    round_request = {
        "contractVersion": "1.0.0",
        "operation": "asset-review",
        "actor": "creator",
        "reason": "Compare the original brand marks on their intended background",
        "expectedBasis": proposed["proposal"]["basisHeads"],
        "proposalHash": proposal_hash,
        "itemId": "mo04",
        "assetIndex": 0,
        "background": "#bcdfed",
        "roots": [{"rootId": "approved-library", "locator": str(root)}],
        "options": [
            selection(root, "logo.png", "approved-mark"),
            selection(root, "different.png", "wrong-mark", subject="Another brand"),
        ],
    }
    document = workspace.raw_dir / "asset-request.json"
    document.write_text(json.dumps(round_request), encoding="utf-8")
    command = [
        "animation",
        "asset-review",
        "--project",
        str(workspace.project_path),
        "--request",
        str(document),
        "--json",
    ]
    assert main([*command, "--request-sha256", "0" * 64]) != 0
    assert not (workspace.raw_dir / "edit/motion/assets").exists()
    capsys.readouterr()
    assert (
        main([*command, "--request-sha256", file_fingerprint(document)["sha256"]]) == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "review-required"
    assert result["rootStatus"] == {"approved-library": "available"}
    assert (workspace.raw_dir / result["contactSheet"]["locator"]).is_file()
    choose = {
        "roundRef": result["roundRef"],
        "disposition": "choose",
        "optionNumber": 2,
    }
    select = {
        "proposalHash": proposal_hash,
        "dispositions": [
            {
                "itemId": "mo04",
                "status": "selected",
                "reason": "Use the reviewed concept",
            }
        ],
        "assetChoices": [choose],
    }
    service = MotionAuthoringService(workspace)
    with pytest.raises(ValueError, match="unresolved"):
        service.select(
            request(workspace, "plan-select", "flagged-option", selection=select)
        )
    choose.update(optionNumber=1, disposition="supply")
    selected = service.select(
        request(workspace, "plan-select", "creator-option", selection=select)
    )
    assert (
        selected["decision"]["assetChoices"][0]["option"]["optionId"] == "approved-mark"
    )
    snapshot = MotionReviewService(workspace).project(service.review_context(selected))
    assert snapshot["items"][0]["assetReadiness"] == "unresolved"
    assert (
        snapshot["storyboardCards"][0]["assets"][0]["review"]["contactSheet"]
        == result["contactSheet"]
    )
    assert not workspace.artifact_path("bmap").exists()
    assert not workspace.artifact_path("tracks").exists()
    verify_application_assets(service, selected)
    (root / "logo.png").write_bytes(b"different PNG bytes")
    with pytest.raises(ValueError, match="bytes changed"):
        verify_application_assets(service, selected)
    with pytest.raises(ValueError, match="bytes changed"):
        service.select(
            request(workspace, "plan-select", "stale-option", selection=select)
        )
    choose["disposition"] = "reject"
    rejected = service.select(
        request(workspace, "plan-select", "reject-option", selection=select)
    )
    rejected_view = MotionReviewService(workspace).project(
        service.review_context(rejected)
    )
    assert rejected_view["items"][0]["assetReadiness"] == "missing"
    assert not workspace.artifact_path("bmap").exists()


def test_mcp_asset_review_binds_selected_request_bytes(tmp_path):
    from avo.mcp.tools.cli_tools import _decision_gate_args, all_bridge_defs

    request_path = tmp_path / "asset-review.json"
    request_path.write_text('{"operation":"asset-review"}', encoding="utf-8")
    tool = next(
        definition
        for definition in all_bridge_defs()
        if definition.spec.name == "avo_animation_asset_review"
    )
    args = {"request": str(request_path)}
    original = _decision_gate_args(tool, args)["_decisionDocumentSha256"]
    request_path.write_text('{"operation":"asset-review"}\n', encoding="utf-8")
    assert _decision_gate_args(tool, args)["_decisionDocumentSha256"] != original
