"""Freeze a bounded validation example and its exact canonical interchange basis."""

import hashlib
import json
from fractions import Fraction
from importlib.resources import files
from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection

from .contracts import (
    content_hash,
    file_fingerprint,
    fingerprint_stage,
    validate_document,
)
from .editor_layout import (
    _loss,
    original_occurrences,
    program_picture_format,
    selected_placements,
)
from .import_layout import seconds
from .motion_authoring import MotionAuthoringService
from .motion_review import MotionReviewService
from .reference_observation import _publish_sheet
from .store import timeline_writer, write_immutable_json

SCHEMA = "avo.editor-handoff.schema.json#/$defs/"
IMPLEMENTATION = "fcp7-xmeml-source-v1"


def target_profiles():
    resource = files("avo.resources.interchange").joinpath("target-profiles.json")
    profiles = json.loads(resource.read_text(encoding="utf-8"))
    for profile in profiles:
        validate_document(profile, SCHEMA + "profile")
    return profiles


def _select_profile(identifier):
    matches = [row for row in target_profiles() if row["id"] == identifier]
    if len(matches) != 1:
        raise ValueError("Select one exact editor target profile")
    return matches[0]


def _admitted_path(value):
    path = Path(value)
    if not path.is_absolute() or value.replace("\\", "/").startswith("//"):
        raise ValueError("Editor interchange needs declared absolute local paths")
    return path.resolve()


def _bind_source(workspace, row, roots):
    expected = row["fingerprint"]
    path = _admitted_path(row.get("locator") or expected["locator"])
    if not any(path.is_relative_to(root) and path != root for root in roots):
        raise ValueError("Editor source is outside the explicitly admitted folders")
    if path.is_relative_to((workspace.raw_dir / "edit").resolve()):
        raise ValueError(
            f"Derived edit media cannot be an original editor source: {path}"
        )
    measured = file_fingerprint(path)
    if (measured["sha256"], measured["sizeBytes"]) != (
        expected["sha256"],
        expected["sizeBytes"],
    ):
        raise ValueError("Original editor source fingerprint changed")
    return {"sourceId": row["sourceId"], "kind": row["kind"], **measured}


def _selected_sources(workspace, cmap, rows, roots, inventory):
    wanted = {row["sourceId"] for row in rows if row["mediaKind"] in {"video", "audio"}}
    if len(wanted) > 128:
        raise ValueError("Editor validation source count exceeds its budget")
    selected = {
        row["sourceId"]: _bind_source(workspace, row, roots)
        for row in cmap["sources"]
        if row["sourceId"] in wanted
    }
    if selected.keys() != wanted:
        raise ValueError("Editor placements lack their original source identities")
    return selected, _probe_sources(selected, inventory)


def _probe_sources(selected, inventory):
    paths = [Path(row["locator"]) for row in selected.values()]
    probe = inventory(list(dict.fromkeys(paths)))["sources"]
    by_path = {Path(row["locator"]).resolve(): row for row in probe}
    if not all(Path(row["locator"]) in by_path for row in selected.values()):
        raise ValueError("Editor source measurement omitted a selected original")
    measured = {
        identifier: by_path[Path(row["locator"])]
        for identifier, row in selected.items()
    }
    for identifier, facts in measured.items():
        if facts["fingerprint"]["sha256"] != selected[identifier]["sha256"]:
            raise ValueError("Original editor source changed during measurement")
    return measured


def _assembly(rows, sources, measured, fps, window):
    files_by_id, lanes, evidence, losses = {}, {}, [], []
    for row in rows:
        try:
            file_id, source, clips = original_occurrences(
                row,
                sources.get(row["sourceId"]),
                measured.get(row["sourceId"]),
                fps,
                window["startFrame"],
            )
        except (ValueError, ZeroDivisionError) as error:
            losses.append(_loss(row, fps, str(error)))
            continue
        files_by_id[file_id] = source
        for output, clip, proof in clips:
            key = (row["kind"], row["order"], row["laneId"], output or 0)
            lane = lanes.setdefault(
                key, {"kind": row["kind"], "outputChannel": output, "clips": []}
            )
            lane["clips"].append(clip)
            evidence.append(proof)
        losses.extend(
            _loss(
                row, fps, "This treatment needs target representation evidence", field
            )
            for field in row["effects"]
        )
        if any(
            any(clock["den"] != 1 for clock in proof["exactFrames"].values())
            for _, _, proof in clips
        ):
            losses.append(
                _loss(
                    row,
                    fps,
                    "Original audio was rounded half-up to the interchange frame grid",
                    "audio-quantization",
                )
            )
    return files_by_id, [lanes[key] for key in sorted(lanes)], evidence, losses


def _cue_coverage(snapshots, window, fps):
    markers, losses = [], []
    for cue in (snapshots.get("bmap") or {}).get("cues", []):
        first = max(seconds(cue["start"]), window["startFrame"] / fps)
        end = min(seconds(cue["end"]), window["endFrameExclusive"] / fps)
        if first >= end:
            continue
        frame = first * fps - window["startFrame"]
        if frame.denominator == 1:
            markers.append(
                {
                    "name": cue["cueId"],
                    "comment": cue.get("intent", ""),
                    "in": frame.numerator,
                    "out": -1,
                }
            )
        losses.append(
            _loss(
                {"window": (first, end), "id": cue["cueId"]},
                fps,
                "Canonical cue treatment requires target representation evidence",
            )
        )
    return markers, losses


def _bounded_window(request):
    value = request["programRate"]
    fps = Fraction(value["num"], value["den"])
    window = request["window"]
    duration = window["endFrameExclusive"] - window["startFrame"]
    if not 0 < duration <= 30 * fps:
        raise ValueError("Editor validation examples must cover at most 30 seconds")
    return window, fps


def _artifact(workspace, relative):
    target = workspace.raw_dir / relative
    if not target.resolve().is_relative_to(workspace.timeline_dir.resolve()):
        raise ValueError("Editor handoff artifact escapes the project timeline")
    return target


def _output_root(workspace):
    root = workspace.timeline_dir.resolve().relative_to(workspace.raw_dir.resolve())
    return (root / "editor-handoff").as_posix()


def _publish_xml(workspace, payload):
    digest = hashlib.sha256(payload).hexdigest()
    relative = f"{_output_root(workspace)}/xml/{digest}.xml"
    target = _artifact(workspace, relative)
    if target.exists():
        if file_fingerprint(target)["sha256"] != digest:
            raise ValueError("Immutable editor interchange XML changed")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _publish_sheet(target, payload)
    return {"locator": relative, "sha256": digest}


class EditorHandoffService:
    def __init__(self, workspace, *, inventory=None, write_xml=None, read_xml=None):
        self.workspace = workspace
        self.inventory = inventory
        self.write_xml = write_xml
        self.read_xml = read_xml

    def prepare(self, request):
        validate_document(request, SCHEMA + "prepareRequest")
        profile = _select_profile(request["profileId"])
        choice = validate_editing_craft_selection(request["selection"])["effective"]
        if (
            choice["handoff"]["mode"] != "editor"
            or choice["handoff"].get("targetProfile") != profile["id"]
        ):
            raise ValueError(
                "Editor interchange requires the exact explicitly selected target"
            )
        if request["mode"] != "validation":
            raise ValueError(
                "Editor target is unqualified. Only validation examples are available."
            )
        window, fps = _bounded_window(request)
        roots = tuple(_admitted_path(value) for value in request["admittedRoots"])
        workspace = self.workspace
        owner = MotionAuthoringService(workspace)
        before = request["expectedBasis"]
        owner._check_heads(before)
        _, snapshots, _ = MotionReviewService(workspace)._metadata()
        if workspace.authority != "canonical" or "cmap" not in snapshots:
            raise ValueError(
                "Editor validation requires the current canonical original-source cut"
            )
        workspace.require_active("cmap")
        bundle, payload = self._measure(request, profile, snapshots, window, fps, roots)
        with timeline_writer(workspace.timeline_dir):
            owner._check_heads(before)
            _verify_originals(bundle["sources"])
            return self._publish(bundle, payload)

    def _measure(self, request, profile, snapshots, window, fps, roots):
        cmap = snapshots["cmap"]
        rows = selected_placements(cmap, fps, window)
        workspace = self.workspace
        with fingerprint_stage(verify_on_exit=True):
            sources, measured = _selected_sources(
                workspace, cmap, rows, roots, self.inventory
            )
            files_by_id, lanes, evidence, losses = _assembly(
                rows, sources, measured, fps, window
            )
        if not evidence:
            raise ValueError(
                "No original-source occurrence is representable in the chosen validation window"
            )
        markers, cue_losses = _cue_coverage(snapshots, window, fps)
        if (cmap.get("layout") or {}).get("displayOrigin") is not None:
            losses.append(
                {
                    "field": "display-origin",
                    "scope": window,
                    "reason": "Original editor display timecode awaits target qualification",
                }
            )
        model = {
            "id": "avo-validation-example",
            "name": "AVO editor validation example",
            "rate": fps,
            "duration": window["endFrameExclusive"] - window["startFrame"],
            "originFrame": window["startFrame"],
            "pictureFormat": program_picture_format(cmap, files_by_id),
            "sources": files_by_id,
            "tracks": lanes,
            "markers": markers,
        }
        xml = self.write_xml(model)
        self.read_xml(xml, roots=roots)
        bundle = {
            "contractVersion": "1.0.0",
            "provider": workspace.project["provider"],
            "videoId": workspace.video_id,
            "status": "validation-only",
            "request": request,
            "profile": profile,
            "profileHash": content_hash(profile),
            "implementation": IMPLEMENTATION,
            "sources": list(sources.values()),
            "occurrences": evidence,
            "losses": [*losses, *cue_losses],
        }
        return bundle, xml

    def _publish(self, bundle, payload):
        workspace = self.workspace
        bundle = {**bundle, "xmlRef": _publish_xml(workspace, payload)}
        validate_document(bundle, SCHEMA + "manifest")
        relative = f"{_output_root(workspace)}/manifests/{content_hash(bundle)}.json"
        path = write_immutable_json(_artifact(workspace, relative), bundle)
        return {
            "status": bundle["status"],
            "handoffRef": {
                "locator": relative,
                "sha256": file_fingerprint(path)["sha256"],
            },
            **bundle,
        }

    def status(self, request):
        validate_document(request, SCHEMA + "statusRequest")
        reference = request.get("handoffRef")
        if reference is None:
            return {"profiles": target_profiles()}
        manifest = load_handoff(self.workspace, reference)
        current = MotionReviewService(self.workspace)._metadata(snapshots=False)[0]
        basis = (
            "current"
            if current == manifest["request"]["expectedBasis"]
            else "historical"
        )
        return {**manifest, "basisStatus": basis}


def _verify_originals(sources):
    for row in sources:
        measured = file_fingerprint(Path(row["locator"]))
        if (measured["sha256"], measured["sizeBytes"]) != (
            row["sha256"],
            row["sizeBytes"],
        ):
            raise ValueError(
                "Original editor source changed before handoff publication"
            )


def load_handoff(workspace, reference):
    relative = reference["locator"]
    if not relative.startswith(f"{_output_root(workspace)}/manifests/"):
        raise ValueError("Select an immutable editor handoff manifest")
    path = _artifact(workspace, relative)
    with path.open("rb") as stream:
        data = stream.read(8 * 1024 * 1024 + 1)
    if (
        len(data) > 8 * 1024 * 1024
        or hashlib.sha256(data).hexdigest() != reference["sha256"]
    ):
        raise ValueError("Editor handoff manifest bytes changed or exceeded budget")
    manifest = json.loads(data)
    validate_document(manifest, SCHEMA + "manifest")
    if content_hash(manifest) != path.stem or (
        manifest["provider"],
        manifest["videoId"],
    ) != (workspace.project["provider"], workspace.video_id):
        raise ValueError("Editor handoff manifest identity changed")
    xml = manifest["xmlRef"]
    if (
        file_fingerprint(_artifact(workspace, xml["locator"]))["sha256"]
        != xml["sha256"]
    ):
        raise ValueError("Editor handoff XML bytes changed")
    return manifest
