"""Canonical exact-frame resolution and immutable still extraction records."""

from __future__ import annotations

import re
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

from .contracts import (
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .media_admission import validate_still_admission
from .store import now_iso, write_immutable_json
from .workspace import TimelineWorkspace


class StillExtractionError(RuntimeError):
    pass


def _fraction(value: dict[str, Any], label: str) -> Fraction:
    try:
        result = Fraction(int(value["num"]), int(value["den"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label} must be an exact rational") from exc
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _source_time(point: dict[str, Any]) -> Fraction:
    return Fraction(int(point["ticks"])) * _fraction(point["timebase"], "timebase")


def _source_frame(time: Fraction, frame_rate: Fraction) -> int:
    frame = time * frame_rate
    if frame.denominator != 1 or frame < 0:
        raise ValueError(
            "canonical source time does not resolve to an exact source frame"
        )
    return frame.numerator


def resolve_program_frame(
    snapshot: dict[str, Any],
    program_frame: int,
    frame_rate: dict[str, Any],
    *,
    side: str | None = None,
) -> dict[str, Any]:
    """Resolve a half-open program frame through the current CMap."""
    if program_frame < 0:
        raise ValueError("program frame must be non-negative")
    if side not in {None, "incoming", "outgoing"}:
        raise ValueError("side must be incoming or outgoing")
    rate = _fraction(frame_rate, "frame rate")
    segments = list(snapshot.get("segments") or [])
    cursor = 0
    for index, segment in enumerate(segments):
        start = _source_time(segment["in"])
        end = _source_time(segment["out"])
        count = (end - start) * rate
        if count.denominator != 1 or count <= 0:
            raise ValueError(
                "CMap segment duration is not integral at the program rate"
            )
        next_cursor = cursor + count.numerator
        if program_frame < next_cursor:
            source_time = start + Fraction(program_frame - cursor, 1) / rate
            return {
                "sourceId": str(segment["sourceId"]),
                "sourceFrame": _source_frame(source_time, rate),
                "sourceTime": source_time,
                "programFrame": program_frame,
                "boundaryDecision": "not-boundary",
            }
        if program_frame == next_cursor and index + 1 < len(segments):
            if side is None:
                raise ValueError("program frame is a cut boundary; side is required")
            chosen = segment if side == "outgoing" else segments[index + 1]
            source_time = (
                _source_time(chosen["out"]) - Fraction(1, 1) / rate
                if side == "outgoing"
                else _source_time(chosen["in"])
            )
            return {
                "sourceId": str(chosen["sourceId"]),
                "sourceFrame": _source_frame(source_time, rate),
                "sourceTime": source_time,
                "programFrame": program_frame,
                "boundaryDecision": side,
            }
        cursor = next_cursor
    raise ValueError(f"program frame is outside the current CMap: {program_frame}")


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return result or "still"


class StillExtractionService:
    def __init__(
        self,
        workspace: TimelineWorkspace,
        *,
        adapter: Any | None = None,
        clock: Callable[[], str] = now_iso,
    ) -> None:
        self.workspace = workspace
        self.adapter = adapter
        self.clock = clock

    def _cmap_snapshot(self) -> dict[str, Any]:
        store = self.workspace.store("cmap")
        index = store.load_index()
        revision_id = index.get("headRevisionId")
        if not revision_id or index.get("activeState") != "valid":
            raise StillExtractionError("current valid CMap revision is required")
        return store.revision(str(revision_id))["snapshot"]

    @staticmethod
    def _source(snapshot: dict[str, Any], source_id: str) -> dict[str, Any]:
        source = next(
            (
                item
                for item in snapshot.get("sources") or []
                if item.get("sourceId") == source_id
            ),
            None,
        )
        if source is None:
            raise StillExtractionError(
                f"source is not registered in current CMap: {source_id}"
            )
        return source

    @staticmethod
    def _verified_path(record: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        expected = record.get("fingerprint") or {}
        path = Path(str(expected.get("locator") or record.get("locator") or ""))
        if not path.is_file():
            raise StillExtractionError(f"still input does not exist: {path}")
        actual = file_fingerprint(path)
        if actual["sha256"] != expected.get("sha256"):
            raise StillExtractionError(f"still input fingerprint mismatch: {path}")
        return path, actual

    def _destination(self, purpose: str, frame: int) -> tuple[str, Path]:
        if purpose == "thumbnail":
            root = self.workspace.raw_dir / "edit" / "delivery" / "thumbnails"
        elif purpose in {"review", "reference"}:
            root = self.workspace.review_dir / "stills"
        else:
            root = self.workspace.timeline_dir / "generated-assets" / "stills"
        suffix = f"-{purpose}-f{frame}-v"
        video_slug = _slug(self.workspace.video_id)[: max(3, 63 - len(suffix) - 3)]
        prefix = f"{video_slug}{suffix}"
        existing_images = {
            path.stem.rsplit("-v", 1)[-1]
            for path in root.glob(f"{prefix}*.png")
            if "-v" in path.stem
        }
        existing_records = {
            path.stem.rsplit("-v", 1)[-1]
            for path in (root / "records").glob(f"{prefix}*.json")
            if "-v" in path.stem
        }
        existing = existing_images | existing_records
        sequence = 1
        while f"{sequence:03d}" in existing:
            sequence += 1
        if sequence > 999:
            raise StillExtractionError("still extraction version space is exhausted")
        extraction_id = f"{prefix}{sequence:03d}"
        return extraction_id, root / f"{extraction_id}.png"

    def extract(
        self,
        *,
        purpose: str,
        source_id: str | None = None,
        source_time_num: int | None = None,
        source_time_den: int | None = None,
        program_frame: int | None = None,
        frame_rate: dict[str, Any] | None = None,
        candidate: Path | None = None,
        candidate_frame: int | None = None,
        candidate_state: str | None = None,
        candidate_sha256: str | None = None,
        side: str | None = None,
        decoded_frame_index: int | None = None,
        color_policy: str | None = None,
        width: int | None = None,
    ) -> dict[str, Any]:
        if self.adapter is None:
            raise StillExtractionError("an exact-still adapter is required")
        modes = sum(
            value is not None for value in (source_id, program_frame, candidate)
        )
        if modes != 1:
            raise ValueError(
                "select exactly one of source, program, or candidate input"
            )
        snapshot = self._cmap_snapshot() if candidate is None else None
        canonical_mapping = None
        explicit_index = decoded_frame_index

        if source_id is not None:
            if source_time_num is None or source_time_den is None:
                raise ValueError("source extraction requires an exact rational time")
            requested = Fraction(source_time_num, source_time_den)
            source = self._source(snapshot or {}, source_id)
            input_path, input_fingerprint = self._verified_path(source)
            input_kind = "raw-source"
            requested_time = {
                "kind": "source-time",
                "numerator": requested.numerator,
                "denominator": requested.denominator,
                "boundarySide": "not-boundary",
            }
        elif program_frame is not None:
            if frame_rate is None:
                raise ValueError("program extraction requires an exact frame rate")
            mapping = resolve_program_frame(
                snapshot or {}, program_frame, frame_rate, side=side
            )
            source = self._source(snapshot or {}, mapping["sourceId"])
            input_path, input_fingerprint = self._verified_path(source)
            requested = mapping["sourceTime"]
            input_kind = "program"
            canonical_mapping = {
                key: mapping[key] for key in ("sourceId", "sourceFrame", "programFrame")
            }
            requested_time = {
                "kind": "program-frame",
                "frame": program_frame,
                "boundarySide": mapping["boundaryDecision"],
            }
        else:
            if candidate_frame is None or candidate_frame < 0:
                raise ValueError("candidate extraction requires a non-negative frame")
            if (
                decoded_frame_index is not None
                and decoded_frame_index != candidate_frame
            ):
                raise ValueError(
                    "candidate frame and decoded frame index must identify the same frame"
                )
            if candidate_state not in {"current", "approved"}:
                raise ValueError("candidate state must be current or approved")
            input_path = Path(candidate or "")
            if not input_path.is_file():
                raise StillExtractionError(f"candidate does not exist: {input_path}")
            input_fingerprint = file_fingerprint(input_path)
            if input_fingerprint["sha256"] != candidate_sha256:
                raise StillExtractionError(
                    f"candidate fingerprint mismatch: {input_path}"
                )
            input_kind = f"{candidate_state}-candidate"
            requested = None
            explicit_index = candidate_frame
            requested_time = {
                "kind": "candidate-frame",
                "frame": candidate_frame,
                "boundarySide": "not-boundary",
            }

        validate_still_admission(purpose=purpose, input_kind=input_kind)
        probe = self.adapter.probe(input_path)
        preview = self.adapter.select_frame(
            probe, requested, decoded_frame_index=explicit_index
        )
        extraction_id, output_path = self._destination(
            purpose, preview["decodedFrameIndex"]
        )
        result = self.adapter.extract(
            input_path,
            output_path,
            requested_time=requested,
            decoded_frame_index=explicit_index,
            color_policy=color_policy,
            width=width,
        )
        if input_kind == "program":
            result["resolvedFrame"]["boundaryDecision"] = requested_time["boundarySide"]
        record = {
            "schemaVersion": "1.0.0",
            "extractionId": extraction_id,
            "purpose": purpose,
            "inputKind": input_kind,
            "inputFingerprint": input_fingerprint,
            "canonicalMapping": canonical_mapping,
            "requestedTime": requested_time,
            "resolvedFrame": result["resolvedFrame"],
            "output": result["output"],
            "media": result["media"],
            "colorPolicy": result["colorPolicy"],
            "approvalState": "candidate",
            "createdAt": self.clock(),
        }
        record["recordHash"] = document_hash_excluding(record, "recordHash")
        validate_document(record, "avo.still-extraction.schema.json")
        write_immutable_json(
            output_path.parent / "records" / f"{extraction_id}.json", record
        )
        return record
