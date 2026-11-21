"""Record exact target observations and verify production handoff readiness."""

import json

from .contracts import content_hash, validate_document
from .editor_feedback_service import (
    MAX_REPORT_BYTES,
    _artifact_bytes,
    _load_inspection,
    _original_model,
    _read_bound,
    _read_return,
    _seal,
    _sources,
)
from .editor_handoff import (
    IMPLEMENTATION,
    SCHEMA,
    _artifact,
    _output_root,
    _select_profile,
    _verify_originals,
    load_handoff,
)
from .store import timeline_writer

TARGET_IDENTITY = ("application", "applicationVersion", "os", "osVersion")


def _review_blockers(evidence, profile):
    observed = {row["check"]: row["result"] for row in evidence["checks"]}
    if len(observed) != len(evidence["checks"]):
        raise ValueError("Each editor qualification check must have one disposition")
    blockers = [
        f"Target review needs verified {key}"
        for key in profile["evidenceRequirements"]
        if observed.get(key) != "verified"
    ]
    if evidence["reviewerDecision"] != "accept-scope":
        blockers.append("Target scope awaits reviewer acceptance")
    drift = evidence["maxCutDriftFrames"]
    if drift is None or not 0 <= drift <= 1:
        blockers.append("Cut drift was unobserved or exceeded one output frame")
    return blockers


def _audio_routes(model):
    return [
        (
            lane["index"],
            lane["outputChannel"],
            [clip["sourceTrack"] for clip in lane["clips"]],
        )
        for lane in model["tracks"]
        if lane["kind"] == "audio" and lane["clips"]
    ]


def _picture_clock(model):
    return (
        model["rate"],
        model["originFrame"],
        [
            (lane["index"], len(lane["clips"]))
            for lane in model["tracks"]
            if lane["kind"] == "video" and lane["clips"]
        ],
    )


def _xml_blockers(baseline, returned, sources):
    baseline_audio = _audio_routes(baseline)
    base_digests = {source["sha256"] for source in baseline["sources"].values()}
    returned_digests = {source["sha256"] for source in sources}
    checks = {
        "The returned XML did not retain the original source identities": (
            bool(base_digests) and base_digests == returned_digests
        ),
        "The returned XML did not retain a matching sequence clock and picture lanes": (
            _picture_clock(baseline) == _picture_clock(returned)
            and returned["duration"] > 0
        ),
        "The fixture or return lacks verified audio routes": bool(baseline_audio)
        and baseline_audio == _audio_routes(returned),
        "The fixture or return lacks sequence markers": bool(baseline["markers"])
        and bool(returned["markers"]),
    }
    return [reason for reason, passed in checks.items() if not passed]


def _assess(service, request, profile):
    workspace = service.workspace
    inspection = _load_inspection(workspace, request["inspectionRef"])
    basis = inspection["input"]["handoffRef"]
    base = load_handoff(workspace, basis)
    receipt = inspection["receipt"]
    evidence = request["evidence"]
    if (
        base["profileHash"] != content_hash(profile)
        or base["implementation"] != IMPLEMENTATION
    ):
        raise ValueError(
            "Editor qualification requires the exact current profile and implementation"
        )
    if any(evidence[key] != profile[key] for key in TARGET_IDENTITY):
        raise ValueError(
            "Editor qualification evidence belongs to a different target version or operating system"
        )
    if (evidence["initialXmlSha256"], evidence["returnedXmlSha256"]) != (
        base["xmlRef"]["sha256"],
        receipt["sha256"],
    ):
        raise ValueError(
            "Editor reviewer observations must bind the exact exported and returned XML"
        )
    if (
        base["request"]["mode"] != "validation"
        or receipt["sha256"] == base["xmlRef"]["sha256"]
    ):
        raise ValueError(
            "Editor qualification requires an independently returned validation example"
        )
    _verify_originals(base["sources"])
    baseline = _original_model(
        service, _artifact_bytes(workspace, base["xmlRef"]), base, base["sources"]
    )
    returned = _read_return(
        service, _artifact_bytes(workspace, receipt), inspection["input"]
    )
    sources = _sources(returned, base["sources"])
    if sources != inspection["sourceFacts"]:
        raise ValueError("Editor qualification source facts changed after inspection")
    return (
        basis,
        receipt,
        [
            *_review_blockers(evidence, profile),
            *_xml_blockers(baseline, returned, sources),
        ],
    )


def qualify_target(service, request):
    validate_document(request, SCHEMA + "qualificationRequest")
    workspace = service.workspace
    profile = _select_profile(request["profileId"])
    basis, receipt, blockers = _assess(service, request, profile)
    result = {
        "provider": workspace.project["provider"],
        "videoId": workspace.video_id,
        "input": request,
        "basisRef": basis,
        "returnedXmlRef": receipt,
        "profileHash": content_hash(profile),
        "implementation": IMPLEMENTATION,
        "status": "unqualified" if blockers else "qualified",
        "blockers": blockers,
    }
    with timeline_writer(workspace.timeline_dir):
        reference = _seal(workspace, result, "qualifications", "qualification")
    return {**result, "qualificationRef": reference}


def _load_qualification(workspace, reference):
    locator = reference["locator"]
    if not locator.startswith(f"{_output_root(workspace)}/qualifications/"):
        raise ValueError("Select a project-owned editor qualification")
    path = _artifact(workspace, locator)
    result = json.loads(_read_bound(path, reference["sha256"], MAX_REPORT_BYTES))
    validate_document(result, SCHEMA + "qualification")
    if content_hash(result) != path.stem or (result["provider"], result["videoId"]) != (
        workspace.project["provider"],
        workspace.video_id,
    ):
        raise ValueError("Editor qualification identity or project changed")
    return result


def require_qualification(service, profile, reference):
    if reference is None:
        raise ValueError(
            "Editor target is unqualified. Supply its reviewed target qualification."
        )
    result = _load_qualification(service.workspace, reference)
    if (
        result["status"] != "qualified"
        or result["blockers"]
        or result["profileHash"] != content_hash(profile)
    ):
        raise ValueError("Editor target is unqualified for this profile")
    basis, receipt, blockers = _assess(service, result["input"], profile)
    if blockers or basis != result["basisRef"] or receipt != result["returnedXmlRef"]:
        raise ValueError("Editor qualification evidence no longer matches the target")
