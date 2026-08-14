"""Structured technical and review-gate QC for Shorts batches."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

from avo import shorts_contract, shorts_media


def evaluate_probe(
    probe: Mapping[str, Any], expected: Mapping[str, Any], *, tolerance_sec: float = .08
) -> list[dict[str, str]]:
    findings = []
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        findings.append({"severity": "error", "code": "missing-video"})
    else:
        if int(video.get("width", 0)) != int(expected["width"]) or int(video.get("height", 0)) != int(expected["height"]):
            findings.append({"severity": "error", "code": "wrong-geometry"})
    if not audio:
        findings.append({"severity": "error", "code": "missing-audio"})
    duration = float((probe.get("format") or {}).get("duration", 0))
    if abs(duration - float(expected["durationSec"])) > tolerance_sec:
        findings.append({"severity": "error", "code": "wrong-duration"})
    return findings


def evaluate_captions(phrases: Iterable[Mapping[str, Any]], duration: float) -> list[dict[str, str]]:
    findings = []
    prior_end = 0.0
    for phrase in phrases:
        start, end = float(phrase["startSec"]), float(phrase["endSec"])
        if start < prior_end - 1e-6 or end > duration + 1e-6:
            findings.append({"severity": "error", "code": "caption-bounds"})
        for word in phrase["words"]:
            if not start <= float(word["highlightEnterSec"]) <= float(word["highlightExitSec"]) <= end:
                findings.append({"severity": "error", "code": "highlight-reset"})
        prior_end = end
    return findings


def insertion_review_findings(item: Mapping[str, Any], watch_reference: str | None) -> list[dict[str, str]]:
    if not item.get("insertion"):
        return []
    if not watch_reference:
        return [{
            "severity": "error", "code": "watch-review-required",
            "message": "freeze/activity scans cannot prove semantic active gameplay",
        }]
    return []


def evaluate_item(
    item: Mapping[str, Any], probe: Mapping[str, Any], *,
    watch_reference: str | None = None,
    black_frames: int = 0, freeze_seconds: float = 0, integrated_lufs: float | None = None,
    output: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected = output or {"width": 1080, "height": 1920}
    findings = [
        *evaluate_probe(probe, {
            "width": expected.get("width", 1080),
            "height": expected.get("height", 1920),
            "durationSec": item["editedDurationSec"],
        }),
        *evaluate_captions(item.get("captions") or [], float(item["editedDurationSec"])),
        *insertion_review_findings(item, watch_reference),
    ]
    if black_frames:
        findings.append({"severity": "error", "code": "black-frames"})
    if freeze_seconds > .5:
        findings.append({"severity": "error", "code": "freeze-risk"})
    if integrated_lufs is not None and not -24 <= integrated_lufs <= -8:
        findings.append({"severity": "error", "code": "loudness-outlier"})
    return {"status": "failed" if any(f["severity"] == "error" for f in findings) else "passed", "findings": findings}


def write_qc_report(path: Path, report: Mapping[str, Any]) -> Path:
    return shorts_contract.atomic_write_json(path, report)


def collect_visual_evidence(project: Path) -> list[dict[str, str]]:
    evidence = []
    for pattern in ("snapshots/*.png", "qc/*contact-sheet*.png"):
        for path in sorted(project.glob(pattern)):
            evidence.append({"path": str(path), "sha256": shorts_media.sha256_file(path)})
    return evidence


def generate_contact_sheet(project: Path, output: Path) -> Path:
    snapshots = sorted((project / "snapshots").glob("*.png"))
    if not snapshots:
        raise ValueError("no snapshots available for contact sheet")
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs = [part for path in snapshots for part in ("-i", str(path))]
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        "-filter_complex", f"hstack=inputs={len(snapshots)}", "-frames:v", "1", str(output),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode or not output.is_file():
        raise RuntimeError(result.stderr or "contact sheet generation failed")
    return output


def qc_proof_artifact(
    item: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    watch_reference: str | None = None,
    output: Mapping[str, Any] | None = None,
    collect_metrics: bool = True,
) -> dict[str, Any]:
    proof = Path(artifact["path"])
    probe = shorts_media.probe_media(proof)
    metrics = shorts_media.analyze_video_metrics(proof) if collect_metrics else {}
    return evaluate_item(
        item,
        probe,
        watch_reference=watch_reference,
        black_frames=int(metrics.get("blackFrames") or 0),
        freeze_seconds=float(metrics.get("freezeSeconds") or 0),
        integrated_lufs=metrics.get("integratedLufs"),
        output=output,
    )
