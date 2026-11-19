"""A native validation example keeps source clocks and original media identities."""

import json
import shutil
import subprocess
from copy import deepcopy
from xml.etree import ElementTree

import pytest
from tests.test_timeline_cmap_service import snapshot, workspace

from avo.adapters.media.fcp7_xml import parse_fcp7_xml, write_fcp7_xml
from avo.adapters.registry import build_cutting_service, build_editor_handoff
from avo.editing_craft import resolve_editing_craft_selection
from avo.engine_cli import main
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.motion_review import MotionReviewService

PROFILE = "premiere-pro-25-0-windows-11-24h2"


def editor_request(ws):
    return {
        "contractVersion": "1.0.0",
        "operation": "prepare",
        "actor": "creator",
        "reason": "Inspect a short original-source interchange example",
        "profileId": PROFILE,
        "mode": "validation",
        "expectedBasis": MotionReviewService(ws).project()["basisHeads"],
        "selection": resolve_editing_craft_selection(
            invocation={"handoff": {"mode": "editor", "targetProfile": PROFILE}}
        ),
        "programRate": {"num": 25, "den": 1},
        "window": {"startFrame": 2, "endFrameExclusive": 21},
        "admittedRoots": [str(ws.raw_dir)],
    }


def _feedback_command(ws, request_file, capsys, operation, data, *, expected_code=0):
    body = {
        "contractVersion": "1.0.0",
        "operation": operation,
        "actor": "creator",
        "reason": "Review a returned edit",
        **data,
    }
    request_file.write_text(json.dumps(body), encoding="utf-8")
    assert (
        main(
            [
                "timeline-export",
                operation,
                "--project",
                str(ws.project_path),
                "--video-id",
                ws.video_id,
                "--request",
                str(request_file),
                "--json",
            ]
        )
        == expected_code
    )
    output = capsys.readouterr()
    return json.loads(output.out if expected_code == 0 else output.err)


@pytest.mark.integration
@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg and FFprobe required",
)
def test_native_validation_preserves_original_picture_and_independent_audio(
    tmp_path, capsys, monkeypatch
):
    ws = workspace(tmp_path)
    source = ws.raw_dir / "original source.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:size=160x96:rate=25:duration=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:sample_rate=48000:duration=1.2",
            "-c:v",
            "mpeg4",
            "-threads:v",
            "1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        timeout=45,
    )
    body = snapshot(source)
    body["sources"][0]["streamMetadata"] = {
        "videoStreamIndex": 0,
        "audioSelection": {
            "streamIndex": 1,
            "channels": [0],
            "sourceLayout": "mono",
            "outputLayout": "dual-mono",
            "sourceSampleRate": 48000,
        },
    }
    CMapService(ws).author(
        body, actor="creator", reason="Make validation example from the original source"
    )
    original = file_fingerprint(source)
    request = editor_request(ws)
    payload = tmp_path / "handoff-request.json"
    command = [
        "timeline-export",
        "prepare",
        "--project",
        str(ws.project_path),
        "--video-id",
        ws.video_id,
        "--request",
        str(payload),
        "--json",
    ]
    payload.write_text(json.dumps({**request, "mode": "production"}), encoding="utf-8")
    assert main(command) == 2
    assert "unqualified" in capsys.readouterr().err.casefold()
    assert not (ws.timeline_dir / "editor-handoff").exists()
    payload.write_text(json.dumps(request), encoding="utf-8")
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "validation-only"
    assert result["profile"]["status"] == "unqualified"
    assert result["sources"][0]["sha256"] == original["sha256"]
    xml = ws.raw_dir / result["xmlRef"]["locator"]
    parsed = parse_fcp7_xml(xml.read_bytes(), roots=[ws.raw_dir])
    video, left, right = parsed["tracks"]
    assert parsed["originFrame"] == 2 and parsed["duration"] == 19
    assert (parsed["pictureFormat"]["width"], parsed["pictureFormat"]["height"]) == (
        160,
        96,
    )
    assert [row["outputChannel"] for row in (left, right)] == [1, 2]
    assert [row["clips"][0]["sourceTrack"] for row in (left, right)] == [1, 1]
    assert video["clips"][0]["in"] == 2 and video["clips"][0]["out"] == 21
    assert {row["locator"] for row in parsed["sources"].values()} == {source}
    assert file_fingerprint(source) == original

    from avo.timeline.editor_retention import retained_editor_files

    request["window"] = {"startFrame": 0, "endFrameExclusive": 25}
    whole = build_editor_handoff(ws).prepare(request)
    whole_xml = ws.raw_dir / whole["xmlRef"]["locator"]
    model = parse_fcp7_xml(whole_xml.read_bytes(), roots=[ws.raw_dir])
    choices = []
    for lane in model["tracks"]:
        (clip,) = lane["clips"]
        for field in ("end", "out"):
            clip[field] -= 2
            choices.append({"id": clip["id"], "field": field, "selection": "returned"})
    returned = tmp_path / "linked-trim.xml"
    returned.write_bytes(write_fcp7_xml(model))
    inspection = _feedback_command(
        ws,
        payload,
        capsys,
        "inspect-feedback",
        {
            "handoffRef": whole["handoffRef"],
            "returnedXml": {
                "locator": str(returned),
                "sha256": file_fingerprint(returned)["sha256"],
            },
            "admittedRoots": [str(ws.raw_dir)],
        },
    )
    review = _feedback_command(
        ws,
        payload,
        capsys,
        "propose-feedback",
        {
            "inspectionRef": inspection["inspectionRef"],
            "expectedBasis": request["expectedBasis"],
        },
    )
    route_request = {
        "proposalRef": review["proposalRef"],
        "expectedBasis": request["expectedBasis"],
        "choices": choices,
    }
    incomplete = _feedback_command(
        ws,
        payload,
        capsys,
        "apply-feedback",
        {**route_request, "choices": choices[:1]},
    )
    assert incomplete["status"] == "manual-review"
    assert incomplete["cuttingProposalRef"] is None
    retained = _feedback_command(
        ws,
        payload,
        capsys,
        "apply-feedback",
        {
            **route_request,
            "choices": [{**choice, "selection": "current"} for choice in choices],
        },
    )
    assert retained["status"] == "current-retained"

    from avo.timeline import editor_feedback_service

    interrupted_proposals = []
    seal = editor_feedback_service._seal

    def interrupt_route(workspace, body, collection, definition):
        if collection == "routes":
            interrupted_proposals.append(body["cuttingProposalRef"])
            raise OSError("fixture interrupted the editor route write")
        return seal(workspace, body, collection, definition)

    with monkeypatch.context() as patch:
        patch.setattr(editor_feedback_service, "_seal", interrupt_route)
        with pytest.raises(OSError, match="interrupted the editor route"):
            editor_feedback_service.apply_feedback(
                build_editor_handoff(ws),
                {
                    "contractVersion": "1.0.0",
                    "operation": "apply-feedback",
                    "actor": "creator",
                    "reason": "Review a returned edit",
                    **route_request,
                },
                cutting_factory=lambda: build_cutting_service(ws),
            )
    assert MotionReviewService(ws).project()["basisHeads"] == request["expectedBasis"]
    route = _feedback_command(ws, payload, capsys, "apply-feedback", route_request)
    assert route["status"] == "cutting-review-required" and route["mutated"] is False
    reference = route["cuttingProposalRef"]
    assert interrupted_proposals == [reference]
    owner = build_cutting_service(ws)
    proposal = owner.store.load_document(reference)["payload"]
    assert proposal["scope"]["editorFeedbackRef"] == review["proposalRef"]
    assert len(proposal["edits"]) == 1
    interval = proposal["edits"][0]["removeRange"]
    assert (interval["startTicks"], interval["endTicksExclusive"]) == (920, 1000)
    assert owner.apply(reference)["status"] == "needs-review"
    assert (
        _feedback_command(ws, payload, capsys, "apply-feedback", route_request)[
            "routeRef"
        ]
        == route["routeRef"]
    )
    assert ws.timeline_dir / "cutting" / reference["locator"] in retained_editor_files(
        ws
    )
    assert MotionReviewService(ws).project()["basisHeads"] == request["expectedBasis"]
    assert file_fingerprint(source) == original


@pytest.mark.integration
def test_placed_validation_preserves_gaps_overlay_order_and_repeated_occurrences(
    tmp_path,
):
    from tests.integration.test_otio_placed_pipeline import _trial

    imported, source, _ = _trial(tmp_path)
    ws = imported.workspace
    request = editor_request(ws)
    request["programRate"] = {"num": 24, "den": 1}
    request["window"] = {"startFrame": 0, "endFrameExclusive": 60}
    original = file_fingerprint(source)
    result = build_editor_handoff(ws).prepare(request)
    parsed = parse_fcp7_xml(
        (ws.raw_dir / result["xmlRef"]["locator"]).read_bytes(), roots=[ws.raw_dir]
    )
    base, upper, left, right = parsed["tracks"]
    assert [(row["start"], row["end"]) for row in base["clips"]] == [(12, 36), (48, 60)]
    assert [(row["start"], row["end"]) for row in upper["clips"]] == [(24, 30)]
    assert base["clips"][0]["fileId"] == base["clips"][1]["fileId"]
    assert [lane["clips"][0]["sourceTrack"] for lane in (left, right)] == [1, 2]
    assert all(row["locator"] == source for row in parsed["sources"].values())
    assert file_fingerprint(source) == original


@pytest.mark.integration
def test_validation_exports_constant_gain_only_for_the_observed_target(tmp_path):
    from tests.integration.test_otio_placed_pipeline import _trial

    imported, source, initial = _trial(tmp_path)
    ws = imported.workspace
    original = file_fingerprint(source)
    body = deepcopy(initial["snapshot"])
    item = next(
        row for row in body["layout"]["placements"] if row["mediaKind"] == "audio"
    )
    item["gainDb"] = -6.020599913279624
    CMapService(ws).author(
        body,
        expected_head_hash=initial["contentHash"],
        actor="creator",
        reason="Set a constant level on one original clip",
    )
    before = MotionReviewService(ws).project()["basisHeads"]

    for profile in (PROFILE, "davinci-resolve-21-0-0-47-windows-11-25h2"):
        request = editor_request(ws)
        request.update(
            profileId=profile,
            selection=resolve_editing_craft_selection(
                invocation={"handoff": {"mode": "editor", "targetProfile": profile}}
            ),
            programRate={"num": 24, "den": 1},
            window={"startFrame": 2, "endFrameExclusive": 60},
        )
        result = build_editor_handoff(ws).prepare(request)
        payload = (ws.raw_dir / result["xmlRef"]["locator"]).read_bytes()
        model = parse_fcp7_xml(payload, roots=[ws.raw_dir])
        routing = ElementTree.fromstring(payload).findall(
            ".//audio/track/clipitem/filter/effect[effectid='audiopan']/parameter/value"
        )
        clips = [
            clip
            for lane in model["tracks"]
            for clip in lane["clips"]
            if clip["id"].startswith(item["placementId"] + "-channel-")
        ]
        assert len(clips) == 2
        losses = [row for row in result["losses"] if row["field"] == "gainDb"]
        if profile == PROFILE:
            assert model["originFrame"] == 2
            assert any(row["field"] == "display-origin" for row in result["losses"])
            assert all("gainDb" not in clip for clip in clips)
            assert len(losses) == 1
            assert routing == []
        else:
            assert model["originFrame"] == 86402
            assert all(row["field"] != "display-origin" for row in result["losses"])
            assert [clip["gainDb"] for clip in clips] == pytest.approx(
                [item["gainDb"]] * 2
            )
            assert losses == []
            assert [int(value.text) for value in routing] == [-1, 1]
        assert result["status"] == "validation-only"
        assert result["profile"]["status"] == "unqualified"
    assert MotionReviewService(ws).project()["basisHeads"] == before
    assert file_fingerprint(source) == original


@pytest.mark.integration
@pytest.mark.parametrize("source_kind", ["raw", "authorial"])
def test_placed_alpha_handoff_requires_an_original_video_source(tmp_path, source_kind):
    from tests.integration.test_otio_placed_pipeline import _trial

    from avo.timeline.lineage import LineageError

    imported, _, initial = _trial(tmp_path)
    ws = imported.workspace
    overlay = ws.raw_dir / "transparent original.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red@0.5:size=128x96:rate=24:duration=3,format=rgba",
            "-threads:v",
            "1",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4444",
            "-pix_fmt",
            "yuva444p10le",
            str(overlay),
        ],
        check=True,
        timeout=45,
    )
    before = file_fingerprint(overlay)
    revised = deepcopy(initial["snapshot"])
    source_id = "original-alpha"
    revised["sources"].append(
        {
            "sourceId": source_id,
            "kind": source_kind,
            "locator": str(overlay),
            "fingerprint": before,
            "streamMetadata": {"videoStreamIndex": 0},
        }
    )
    lanes = revised["layout"]["tracks"]
    lane = max(
        (item for item in lanes if item["kind"] == "video"),
        key=lambda item: item["order"],
    )
    placement = next(
        row
        for row in revised["layout"]["placements"]
        if row["trackId"] == lane["trackId"]
    )
    placement["sourceId"] = source_id
    for name in ("in", "out"):
        placement[name]["sourceId"] = source_id
    authoring = {
        "actor": "creator",
        "reason": "Select an original alpha layer on the upper picture lane",
        "expected_head_hash": initial["contentHash"],
    }
    if source_kind == "authorial":
        with pytest.raises(LineageError, match="Moving media requires raw media"):
            CMapService(ws).author(revised, **authoring)
        assert ws.store("cmap").head_hash() == initial["contentHash"]
        return
    CMapService(ws).author(revised, **authoring)
    request = editor_request(ws)
    request["programRate"] = {"num": 24, "den": 1}
    request["window"] = {"startFrame": 0, "endFrameExclusive": 60}

    result = build_editor_handoff(ws).prepare(request)
    payload = (ws.raw_dir / result["xmlRef"]["locator"]).read_bytes()
    parsed = parse_fcp7_xml(payload, roots=[ws.raw_dir])
    (clip,) = parsed["tracks"][1]["clips"]
    assert (clip["start"], clip["end"], clip["in"], clip["out"]) == (24, 30, 0, 6)
    assert parsed["sources"][clip["fileId"]]["locator"] == overlay
    selected = next(row for row in result["sources"] if row["sourceId"] == source_id)
    assert selected["sha256"] == before["sha256"] and selected["kind"] == source_kind
    assert file_fingerprint(overlay) == before


@pytest.mark.integration
def test_returned_edit_stays_a_review_proposal_and_preserves_original_bytes(
    tmp_path, capsys
):
    from tests.integration.test_otio_placed_pipeline import _trial

    imported, source, _ = _trial(tmp_path)
    ws = imported.workspace
    request = editor_request(ws)
    request["programRate"] = {"num": 24, "den": 1}
    request["window"] = {"startFrame": 0, "endFrameExclusive": 60}
    original = file_fingerprint(source)
    result = build_editor_handoff(ws).prepare(request)
    xml = ws.raw_dir / result["xmlRef"]["locator"]
    model = parse_fcp7_xml(xml.read_bytes(), roots=[ws.raw_dir])
    edited = model["tracks"][0]["clips"][0]
    edited["end"] -= 2
    edited["out"] -= 2
    returned = tmp_path / "returned.xml"
    returned.write_bytes(write_fcp7_xml(model))
    returned_sha = file_fingerprint(returned)["sha256"]
    request_file = tmp_path / "feedback-request.json"

    def run(operation, data, *, expected_code=0):
        body = {
            "contractVersion": "1.0.0",
            "operation": operation,
            "actor": "creator",
            "reason": "Review a returned edit",
            **data,
        }
        request_file.write_text(json.dumps(body), encoding="utf-8")
        assert (
            main(
                [
                    "timeline-export",
                    operation,
                    "--project",
                    str(ws.project_path),
                    "--video-id",
                    ws.video_id,
                    "--request",
                    str(request_file),
                    "--json",
                ]
            )
            == expected_code
        )
        output = capsys.readouterr()
        return json.loads(output.out if expected_code == 0 else output.err)

    inspection = run(
        "inspect-feedback",
        {
            "handoffRef": result["handoffRef"],
            "returnedXml": {"locator": str(returned), "sha256": returned_sha},
            "admittedRoots": [str(ws.raw_dir)],
        },
    )
    assert inspection["status"] == "inspected"
    assert all(row["status"] == "matches-original" for row in inspection["sourceFacts"])
    assert (
        ws.raw_dir / inspection["returnedXmlRef"]["locator"]
    ).read_bytes() == returned.read_bytes()
    proposed = {
        "inspectionRef": inspection["inspectionRef"],
        "expectedBasis": request["expectedBasis"],
    }
    review = run("propose-feedback", proposed)
    assert review["status"] == "review-required"
    assert {(row["id"], row["field"]) for row in review["changes"]["proposals"]} == {
        (edited["id"], "end"),
        (edited["id"], "out"),
    }
    assert not review["changes"]["conflicts"]
    assert run("propose-feedback", proposed)["proposalRef"] == review["proposalRef"]
    manual = run(
        "apply-feedback",
        {
            "proposalRef": review["proposalRef"],
            "expectedBasis": request["expectedBasis"],
            "choices": [
                {"id": edited["id"], "field": field, "selection": "returned"}
                for field in ("end", "out")
            ],
        },
    )
    assert manual["status"] == "manual-review"
    assert manual["cuttingProposalRef"] is None
    assert MotionReviewService(ws).project()["basisHeads"] == request["expectedBasis"]
    assert file_fingerprint(source) == original

    profile = result["profile"]
    qualification_request = {
        "profileId": profile["id"],
        "inspectionRef": inspection["inspectionRef"],
        "evidence": {
            "contractVersion": "1.0.0",
            **{
                key: profile[key]
                for key in ("application", "applicationVersion", "os", "osVersion")
            },
            "initialXmlSha256": result["xmlRef"]["sha256"],
            "returnedXmlSha256": returned_sha,
            "checks": [],
            "maxCutDriftFrames": None,
            "reviewerDecision": "needs-work",
            "reviewer": "fixture operator",
        },
    }
    qualification = run("qualify-target", qualification_request)
    assert qualification["status"] == "unqualified"
    assert "Target review needs verified target-opened" in qualification["blockers"]
    assert "The fixture or return lacks sequence markers" in qualification["blockers"]
    bad_target = {**qualification_request["evidence"], "osVersion": "different version"}
    blocked_qualification = run(
        "qualify-target",
        {**qualification_request, "evidence": bad_target},
        expected_code=2,
    )
    assert (
        "different target version or operating system"
        in blocked_qualification["message"]
    )
    with pytest.raises(ValueError, match="unqualified"):
        build_editor_handoff(ws).prepare(
            {
                **request,
                "mode": "production",
                "qualificationRef": qualification["qualificationRef"],
            }
        )

    returned.write_bytes(b"<?xml version='1.0'?><unrecognized-editor-format/>")
    rejected = run(
        "inspect-feedback",
        {
            "handoffRef": result["handoffRef"],
            "returnedXml": {
                "locator": str(returned),
                "sha256": file_fingerprint(returned)["sha256"],
            },
            "admittedRoots": [str(ws.raw_dir)],
        },
    )
    assert rejected["status"] == "unsupported"
    assert (
        ws.raw_dir / rejected["returnedXmlRef"]["locator"]
    ).read_bytes() == returned.read_bytes()
    blocked = run(
        "propose-feedback",
        {**proposed, "inspectionRef": rejected["inspectionRef"]},
        expected_code=2,
    )
    assert "Unsupported returned editor bytes" in blocked["message"]

    from avo.project_inventory import _fallback_reconstruction_metadata
    from avo.timeline.editor_retention import retained_editor_files
    from avo.timeline.reconstruction import _required_files

    orphan = xml.parent / "not-referenced.xml"
    orphan.write_bytes(b"interrupted export residue")
    kept = retained_editor_files(ws)
    expected = (
        result["handoffRef"],
        result["xmlRef"],
        inspection["inspectionRef"],
        inspection["returnedXmlRef"],
        review["proposalRef"],
        rejected["inspectionRef"],
        rejected["returnedXmlRef"],
        qualification["qualificationRef"],
        manual["routeRef"],
    )
    assert all(kept[ws.raw_dir / ref["locator"]] == ref["sha256"] for ref in expected)
    assert orphan not in kept
    bundle_inputs = _required_files(ws.raw_dir, [], workspace=ws)
    assert kept.items() <= bundle_inputs.items()
    inventory = _fallback_reconstruction_metadata(ws.raw_dir, ws.timeline_dir, ws)
    assert set(kept) <= set(inventory) and orphan not in inventory
    xml.write_bytes(b"changed exported artifact")
    with pytest.raises(ValueError, match="identity changed"):
        retained_editor_files(ws)
