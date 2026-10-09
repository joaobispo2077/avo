"""Render a generated EDL projection through the AVO ffmpeg pipeline."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from avo.timeline.contracts import content_hash, file_fingerprint

_MODE_BY_DIMENSIONS = {
    (1280, 720): "--draft",
    (1920, 1080): "--preview",
    (3840, 2160): "--youtube-4k",
}
_YOUTUBE_4K_PROFILES = {"4k", "master-4k", "youtube-4k", "youtube_4k"}


def _render_mode_args(
    profile: str,
    render_contract: dict[str, Any] | None,
) -> list[str]:
    """Map a render contract or profile name to one avo.render mode flag."""
    dimensions = (
        (
            int(render_contract.get("width") or 0),
            int(render_contract.get("height") or 0),
        )
        if render_contract
        else None
    )
    if dimensions:
        mode = _MODE_BY_DIMENSIONS.get(dimensions)
        if mode is None:
            raise RuntimeError(
                "unsupported render contract dimensions: "
                f"{dimensions[0]}x{dimensions[1]}"
            )
        return [mode]
    if profile == "draft":
        return ["--draft"]
    if profile == "preview":
        return ["--preview"]
    if profile in _YOUTUBE_4K_PROFILES:
        return ["--youtube-4k"]
    return []


def _reject_contract_mismatch(
    media: dict[str, Any] | None,
    render_contract: dict[str, Any] | None,
) -> None:
    """Fail when probed picture geometry disagrees with the render contract."""
    if render_contract and media:
        expected_fps = float(render_contract["frameRate"]["num"]) / float(
            render_contract["frameRate"]["den"]
        )
        tolerance = float(render_contract["frameRate"].get("tolerance") or 0)
        mismatches = [
            field
            for field in ("width", "height")
            if int(media[field]) != int(render_contract[field])
        ]
        if abs(float(media["frameRate"]) - expected_fps) > tolerance:
            mismatches.append("frameRate")
        if mismatches:
            raise RuntimeError(
                "rendered output does not match render contract: "
                + ", ".join(mismatches)
            )


class TimelineRenderAdapter:
    """TimelineRenderPort: projection JSON in, hash-bound media out."""

    def __init__(self, *, proof_executor: Any | None = None) -> None:
        if proof_executor is None:
            from .proof_executor import execute_ffmpeg_proof

            proof_executor = execute_ffmpeg_proof
        self.proof_executor = proof_executor

    def proof_tool_readiness(self, proof_plan: dict[str, Any]) -> dict[str, bool]:
        adapters = {
            str(item.get("adapterId") or "").casefold()
            for item in proof_plan.get("implementationRefs") or []
        }
        return {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "hyperframes": (
                shutil.which("hyperframes") is not None
                if any("hyperframes" in item for item in adapters)
                else True
            ),
            "proof-plan-executor": self.proof_executor is not None,
        }

    def render_proof_plan(
        self,
        proof_plan: dict[str, Any],
        output: Path,
        *,
        window: dict[str, int] | None,
    ) -> dict[str, Any]:
        """Pass the immutable operation/event graph to one registered executor."""
        from avo.timeline.contracts import document_hash_excluding, validate_document

        validate_document(proof_plan, "avo.proof-plan.schema.json")
        if proof_plan.get("proofPlanHash") != document_hash_excluding(
            proof_plan, "proofPlanHash"
        ):
            raise RuntimeError("ProofPlan hash mismatch")
        if self.proof_executor is None:
            raise RuntimeError("ProofPlan execution backend is not configured")
        execution = {
            "proofPlanId": proof_plan["proofPlanId"],
            "proofPlanHash": proof_plan["proofPlanHash"],
            "videoGraph": deepcopy(proof_plan["videoGraph"]),
            "audioGraph": deepcopy(proof_plan["audioGraph"]),
            "events": deepcopy(proof_plan["events"]),
            "implementationRefs": deepcopy(proof_plan["implementationRefs"]),
            "output": deepcopy(proof_plan["output"]),
            "renderProfile": proof_plan["renderProfile"],
            "canonicalInputLock": deepcopy(proof_plan["canonicalInputLock"]),
            "lineagePolicy": deepcopy(proof_plan["lineagePolicy"]),
            "window": deepcopy(window),
        }
        graph_hash = content_hash(
            {
                key: execution[key]
                for key in (
                    "videoGraph",
                    "audioGraph",
                    "events",
                    "implementationRefs",
                )
            }
        )
        result = self.proof_executor(execution, Path(output))
        if not isinstance(result, dict):
            raise RuntimeError("ProofPlan executor returned an invalid result")
        return {
            **result,
            "graphHash": graph_hash,
            "proofPlanHash": proof_plan["proofPlanHash"],
            "window": deepcopy(window),
        }

    def render(self, projection: Path, output: Path, **request: Any) -> dict[str, Any]:
        from avo.adapters.media.audio_tracks import compile_continuous_audio_graph
        from avo.render import main as render_main

        projection = Path(projection)
        output = Path(output)
        profile = str(
            request.get("profile") or request.get("render_profile") or "draft"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        audio_graph = request.get("audio_graph")
        compiled_audio = None
        if audio_graph is not None:
            compiled_audio = compile_continuous_audio_graph(
                audio_graph.get("nodes") or [],
                audio_graph.get("operations") or [],
                sample_rate=int(audio_graph.get("sampleRate") or 48_000),
            )
        render_contract = request.get("render_contract")
        argv = [
            "avo.render",
            str(projection),
            "-o",
            str(output),
            "--no-subtitles",
            *_render_mode_args(profile, render_contract),
        ]
        previous = sys.argv
        try:
            sys.argv = argv
            render_main()
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise RuntimeError(f"timeline render failed: {output}") from exc
        finally:
            sys.argv = previous
        fingerprint = file_fingerprint(output)
        media = self._probe_output(output) if render_contract else None
        _reject_contract_mismatch(media, render_contract)
        return {
            "status": "pass",
            "output": {**fingerprint, "locator": str(output)},
            "path": str(output),
            "renderProfile": profile,
            "renderContractHash": (
                content_hash(render_contract) if render_contract is not None else None
            ),
            "producer": {"name": "avo.render", "version": "1"},
            "media": media,
            "audioGraphHash": (
                compiled_audio["graphHash"] if compiled_audio is not None else None
            ),
            "audioEncodeCount": 1 if compiled_audio is not None else None,
        }

    @staticmethod
    def _probe_output(path: Path) -> dict[str, Any]:
        probe = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,r_frame_rate",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        stream = (probe.get("streams") or [None])[0]
        if not stream:
            raise RuntimeError(f"rendered output has no video stream: {path}")
        numerator, denominator = str(stream["r_frame_rate"]).split("/", 1)
        return {
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "frameRate": float(numerator) / float(denominator),
        }
