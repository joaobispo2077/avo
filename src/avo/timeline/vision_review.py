"""Pure planning contracts for context-budgeted long-form vision review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import content_hash


class VisionReviewError(ValueError):
    """Raised when vision review cannot preserve identity, coverage, or budget."""


_GIB = 1024**3
_RANGE_REQUIRED_CATEGORIES = {
    "pacing",
    "movement",
    "continuity",
    "caption",
    "visual-quality",
}
_FINDING_STATUSES = {"open", "corroborated", "dismissed", "resolved", "needs-human"}
_FINDING_CATEGORIES = {
    "layout",
    "pacing",
    "movement",
    "continuity",
    "privacy",
    "caption",
    "visual-quality",
    "editorial",
    "factual-risk",
    "rights",
    "accessibility",
    "technical",
    "other",
}
_FINDING_SEVERITIES = {"info", "warning", "blocking", "unknown"}


def build_capability_snapshot(
    *,
    configured_model: str,
    endpoint_identity: dict[str, Any],
    probe: dict[str, Any],
    resource_policy: dict[str, Any],
    conservative_context_limit: int | None = None,
    estimator_name: str = "avo-visual-budget",
    estimator_version: str = "1",
) -> dict[str, Any]:
    """Build an immutable snapshot from a successful live endpoint probe."""
    served = str(probe.get("servedModel") or "").strip()
    if not probe.get("success"):
        raise VisionReviewError("vision endpoint live probe failed")
    for field in ("requestHash", "responseHash", "probedAt", "latencyMs"):
        if probe.get(field) is None:
            raise VisionReviewError(f"vision endpoint probe is missing {field}")
    for field in ("requestHash", "responseHash"):
        value = str(probe[field])
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise VisionReviewError(f"vision endpoint probe has invalid {field}")
    if not served or served != configured_model:
        raise VisionReviewError(
            f"served model {served!r} does not match configured model {configured_model!r}"
        )
    if probe.get("supportsVision") is not True:
        raise VisionReviewError("served model did not prove live vision support")
    observed_context = probe.get("effectiveContextTokens")
    if observed_context is not None:
        effective_context = int(observed_context)
        provenance = "runtime-observed"
    elif conservative_context_limit is not None:
        effective_context = int(conservative_context_limit)
        provenance = "policy-conservative-limit"
    else:
        raise VisionReviewError(
            "effective runtime context is unknown and no conservative context limit was declared"
        )
    if effective_context <= 0:
        raise VisionReviewError("effective runtime context must be positive")
    policy = deepcopy(resource_policy)
    if policy.get("operatorManagedLifecycle") is not True:
        raise VisionReviewError("vision model lifecycle must remain operator-managed")
    if int(policy.get("concurrency") or 0) != 1:
        raise VisionReviewError("local vision review requires concurrency one")
    vram = policy.get("vramCeilingBytes")
    if configured_model == "qwen3.5-4b" and (vram is None or int(vram) > 7 * _GIB):
        raise VisionReviewError(
            "qwen3.5-4b must stay within the declared 7 GB VRAM policy"
        )
    snapshot = {
        "configuredModel": configured_model,
        "servedModel": served,
        "endpointIdentity": deepcopy(endpoint_identity),
        "supportsVision": True,
        "effectiveContextTokens": effective_context,
        "contextProvenance": provenance,
        "maxOutputTokens": probe.get("maxOutputTokens"),
        "imageCapabilities": {
            "maxImages": probe.get("maxImages"),
            "detailModes": list(probe.get("detailModes") or []),
            "maxWidth": probe.get("maxWidth"),
            "maxHeight": probe.get("maxHeight"),
            "estimatorName": estimator_name,
            "estimatorVersion": estimator_version,
        },
        "resourcePolicy": policy,
        "probe": {
            "probedAt": probe.get("probedAt"),
            "requestHash": probe.get("requestHash"),
            "responseHash": probe.get("responseHash"),
            "latencyMs": probe.get("latencyMs"),
            "success": True,
        },
    }
    identity = content_hash(snapshot)
    snapshot["snapshotId"] = f"vision-cap-{identity[:16]}"
    snapshot["identityHash"] = identity
    return snapshot


def compile_context_budget(
    *,
    effective_context_tokens: int,
    instruction_tokens: int,
    rubric_tokens: int,
    transcript_tokens: int,
    carry_forward_tokens: int,
    response_reserve_tokens: int,
    safety_margin_tokens: int,
    visual_tokens_per_frame: int,
    required_frames: int,
    backend_image_limit: int | None = None,
    safety_frame_ceiling: int | None = None,
    estimator_name: str = "avo-visual-budget",
    estimator_version: str = "1",
    image_detail: str = "low",
    image_width: int | None = None,
    image_height: int | None = None,
) -> dict[str, Any]:
    """Allocate text, output, safety, and estimated visual tokens per pass."""
    components = {
        "instructionTokens": instruction_tokens,
        "rubricTokens": rubric_tokens,
        "transcriptTokens": transcript_tokens,
        "carryForwardTokens": carry_forward_tokens,
        "outputReserveTokens": response_reserve_tokens,
        "safetyMarginTokens": safety_margin_tokens,
    }
    if any(isinstance(value, bool) or int(value) < 0 for value in components.values()):
        raise VisionReviewError("token budget components must be non-negative integers")
    if visual_tokens_per_frame <= 0 or required_frames < 0:
        raise VisionReviewError(
            "visual token cost must be positive and frame count non-negative"
        )
    fixed = sum(int(value) for value in components.values())
    available = int(effective_context_tokens) - fixed
    if available <= 0:
        raise VisionReviewError("non-visual reserves exhaust the effective context")
    limits = [required_frames, available // visual_tokens_per_frame]
    if backend_image_limit is not None:
        limits.append(int(backend_image_limit))
    if safety_frame_ceiling is not None:
        limits.append(int(safety_frame_ceiling))
    max_frames = max(0, min(limits))
    if required_frames and max_frames == 0:
        raise VisionReviewError("no visual frames fit the effective context budget")
    visual_tokens = max_frames * visual_tokens_per_frame
    return {
        **components,
        "visualTokens": visual_tokens,
        "totalTokens": fixed + visual_tokens,
        "availableVisualTokens": available,
        "visualTokensPerFrame": visual_tokens_per_frame,
        "maxFrames": max_frames,
        "estimator": {"name": estimator_name, "version": estimator_version},
        "imagePolicy": {
            "detail": image_detail,
            "width": image_width,
            "height": image_height,
        },
    }


def _sample_section(section: dict[str, Any]) -> list[int]:
    start = int(section["startFrame"])
    end = int(section["endFrameExclusive"])
    if start < 0 or end <= start:
        raise VisionReviewError(f"invalid section range: {section.get('sectionId')}")
    return [start, start + (end - start - 1) // 2, end - 1]


def compile_review_coverage(
    *,
    duration_frames: int,
    sections: list[dict[str, Any]],
    required_windows: list[dict[str, Any]],
    max_frames_per_pass: int,
    story_checkpoints: list[int] | None = None,
    repair_windows: list[dict[str, Any]] | None = None,
    comparison_windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile deterministic sparse section coverage and dense risk windows."""
    if duration_frames <= 0 or max_frames_per_pass <= 0 or not sections:
        raise VisionReviewError(
            "duration, sections, and pass frame budget are required"
        )
    sparse_frames = sorted(
        {
            0,
            duration_frames - 1,
            *(int(frame) for frame in (story_checkpoints or [])),
            *(frame for section in sections for frame in _sample_section(section)),
        }
    )
    if any(frame < 0 or frame >= duration_frames for frame in sparse_frames):
        raise VisionReviewError("story/payoff checkpoint is outside the program")
    passes: list[dict[str, Any]] = []
    holes: list[dict[str, Any]] = []
    for index in range(0, len(sparse_frames), max_frames_per_pass):
        frames = sparse_frames[index : index + max_frames_per_pass]
        passes.append(
            {
                "passId": f"sparse-{index // max_frames_per_pass + 1}",
                "kind": "sparse-overview",
                "sampleFrames": frames,
                "requiredWindowIds": [],
            }
        )
    for kind, windows in (
        ("repair", repair_windows or []),
        ("comparison", comparison_windows or []),
    ):
        for window in sorted(windows, key=lambda item: str(item["windowId"])):
            start = int(window["startFrame"])
            end = int(window["endFrameExclusive"])
            if start < 0 or end <= start or end > duration_frames:
                raise VisionReviewError(f"invalid {kind} window: {window['windowId']}")
            frames = list(
                dict.fromkeys([start, start + (end - start - 1) // 2, end - 1])
            )
            if len(frames) > max_frames_per_pass:
                holes.append(
                    {
                        "windowId": window["windowId"],
                        "mandatory": bool(window.get("mandatory", True)),
                        "reason": f"{kind}-window-exceeds-pass-budget",
                    }
                )
                continue
            passes.append(
                {
                    "passId": f"{kind}-{window['windowId']}",
                    "kind": kind,
                    "sampleFrames": frames,
                    "requiredWindowIds": [window["windowId"]],
                }
            )
    dense_passes: list[dict[str, Any]] = []
    for window in sorted(required_windows, key=lambda item: str(item["windowId"])):
        start = int(window["startFrame"])
        end = int(window["endFrameExclusive"])
        if start < 0 or end <= start or end > duration_frames:
            raise VisionReviewError(f"invalid required window: {window['windowId']}")
        if max_frames_per_pass < 2:
            holes.append(
                {
                    "windowId": window["windowId"],
                    "mandatory": bool(window.get("mandatory", True)),
                    "reason": "boundary-endpoints-exceed-pass-budget",
                }
            )
            continue
        frames = list(dict.fromkeys([start, start + (end - start - 1) // 2, end - 1]))
        if len(frames) > max_frames_per_pass:
            frames = [frames[0], frames[-1]]
        target = next(
            (
                item
                for item in dense_passes
                if len(set(item["sampleFrames"]) | set(frames)) <= max_frames_per_pass
            ),
            None,
        )
        if target is None:
            dense_passes.append(
                {
                    "passId": f"dense-{window['windowId']}",
                    "kind": "dense-window",
                    "sampleFrames": frames,
                    "requiredWindowIds": [window["windowId"]],
                    "riskClasses": list(window.get("riskClasses") or []),
                    "boundaryPolicy": {
                        "mode": "explicit-endpoints",
                        "overlapFrames": 0,
                    },
                }
            )
        else:
            target["sampleFrames"] = sorted(set(target["sampleFrames"]) | set(frames))
            target["requiredWindowIds"].append(window["windowId"])
            target["riskClasses"] = sorted(
                set(target["riskClasses"]) | set(window.get("riskClasses") or [])
            )
    passes.extend(dense_passes)
    pass_order = {
        "sparse-overview": 0,
        "dense-window": 1,
        "repair": 2,
        "comparison": 3,
    }
    passes.sort(key=lambda item: pass_order[item["kind"]])
    return {
        "passes": passes,
        "coverageHoles": holes,
        "requiredWindowIds": [item["windowId"] for item in required_windows],
        "coverageBySection": {
            str(section["sectionId"]): {
                "required": 3,
                "planned": len(set(_sample_section(section))),
            }
            for section in sections
        },
        "coverageByRiskClass": {
            risk: {
                "required": sum(
                    risk in (item.get("riskClasses") or []) for item in required_windows
                ),
                "planned": sum(
                    risk in (item.get("riskClasses") or [])
                    and not any(hole["windowId"] == item["windowId"] for hole in holes)
                    for item in required_windows
                ),
            }
            for risk in sorted(
                {
                    risk
                    for item in required_windows
                    for risk in (item.get("riskClasses") or [])
                }
            )
        },
        "samplingMode": "sparse-by-section+dense-risk",
    }


def validate_vision_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Validate the strict evidence-bearing subset needed before aggregation."""
    required = {
        "schemaVersion",
        "findingId",
        "category",
        "severity",
        "confidence",
        "programRange",
        "evidenceRefs",
        "criterionIds",
        "obligationIds",
        "observed",
        "expected",
        "whyItMatters",
        "alternativeExplanations",
        "message",
        "suggestedAction",
        "requiresHuman",
        "status",
        "humanDisposition",
    }
    missing = sorted(required - finding.keys())
    if missing:
        raise VisionReviewError(f"vision finding missing fields: {missing}")
    allowed = required | {"aliases"}
    extras = sorted(finding.keys() - allowed)
    if extras:
        raise VisionReviewError(f"vision finding has unsupported fields: {extras}")
    if finding["schemaVersion"] != "1.0.0":
        raise VisionReviewError("unsupported vision finding schema")
    if finding["category"] not in _FINDING_CATEGORIES:
        raise VisionReviewError("invalid vision finding category")
    if finding["severity"] not in _FINDING_SEVERITIES:
        raise VisionReviewError("invalid vision finding severity")
    confidence = finding["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise VisionReviewError(
            "vision finding confidence must be between zero and one"
        )
    if not finding["evidenceRefs"]:
        raise VisionReviewError("vision finding requires temporal evidence references")
    if any(
        not isinstance(item, dict)
        or not {"kind", "artifactId", "sha256"}.issubset(item)
        or len(str(item["sha256"])) != 64
        for item in finding["evidenceRefs"]
    ):
        raise VisionReviewError("vision finding evidence references are invalid")
    if finding["status"] not in _FINDING_STATUSES:
        raise VisionReviewError("invalid vision finding status")
    if (
        finding["category"] in _RANGE_REQUIRED_CATEGORIES
        and not finding["programRange"]
    ):
        raise VisionReviewError("vision finding category requires a program range")
    program_range = finding["programRange"]
    if program_range is not None and (
        int(program_range.get("startFrame", -1)) < 0
        or int(program_range.get("endFrameExclusive", -1))
        <= int(program_range.get("startFrame", -1))
    ):
        raise VisionReviewError("vision finding has an invalid program range")
    if finding["status"] == "needs-human" and finding["requiresHuman"] is not True:
        raise VisionReviewError("needs-human finding must require human review")
    if (
        finding["status"] in {"dismissed", "resolved"}
        and not finding["humanDisposition"]
    ):
        raise VisionReviewError("closed finding requires human disposition")
    return deepcopy(finding)


def aggregate_finding_status(
    findings: list[dict[str, Any]],
    *,
    required_passes_complete: bool,
    stale_contract: bool = False,
) -> str:
    """Apply aggregate precedence without reviving dismissed false positives."""
    if stale_contract or not required_passes_complete:
        return "blocked"
    checked = [validate_vision_finding(item) for item in findings]
    active = [
        item for item in checked if item["status"] not in {"dismissed", "resolved"}
    ]
    if any(
        item["severity"] == "blocking" and item["status"] == "corroborated"
        for item in active
    ):
        return "fail"
    if any(item["requiresHuman"] or item["status"] == "needs-human" for item in active):
        return "needs-human-judgment"
    return "pass"


def _overlaps(left: dict[str, int], right: dict[str, int]) -> bool:
    return int(left["startFrame"]) < int(right["endFrameExclusive"]) and int(
        right["startFrame"]
    ) < int(left["endFrameExclusive"])


def review_section_pacing(
    sections: list[dict[str, Any]], metrics_by_section: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Evaluate declared section-purpose symptoms, never one universal cut rate."""
    findings: list[dict[str, Any]] = []
    for section in sections:
        section_id = str(section["sectionId"])
        metrics = metrics_by_section.get(section_id) or {}
        common = {
            "sectionId": section_id,
            "formatRole": section["formatRole"],
            "purpose": section["purpose"],
            "targetDensity": section["targetDensity"],
        }
        if float(metrics.get("repeatedContentSeconds") or 0) > 5:
            findings.append({**common, "code": "repetition"})
        if (
            float(metrics.get("requiredReadingSeconds") or 0)
            > float(metrics.get("cardDurationSeconds") or 0)
            > 0
        ):
            findings.append({**common, "code": "rushed-comprehension"})
        protected = list(section.get("protectedPauses") or [])
        for silence in metrics.get("silenceRanges") or []:
            if not any(_overlaps(silence, pause) for pause in protected):
                findings.append({**common, "code": "dead-air", "programRange": silence})
    return findings


def fuse_protected_event_evidence(
    *, event_id: str, kind: str, visual_status: str, deterministic_status: str
) -> dict[str, Any]:
    """Fuse visible action with transcript/waveform evidence conservatively."""
    if kind not in {"speech", "tactile"}:
        raise VisionReviewError("protected event must be speech or tactile")
    if visual_status == deterministic_status == "pass":
        status, severity = "pass", "info"
    elif visual_status == deterministic_status == "fail":
        status, severity = "corroborated", "blocking"
    else:
        status, severity = "needs-human-judgment", "unknown"
    return {
        "eventId": event_id,
        "kind": kind,
        "visualStatus": visual_status,
        "deterministicStatus": deterministic_status,
        "status": status,
        "severity": severity,
    }


def schedule_review_resources(
    jobs: list[dict[str, Any]],
    *,
    vram_ceiling_bytes: int,
    allowed_co_residency: list[str],
    concurrency: int,
    operator_managed_lifecycle: bool,
) -> dict[str, Any]:
    """Schedule CPU/GPU work without managing or substituting model lifecycles."""
    if not operator_managed_lifecycle:
        raise VisionReviewError("vision model lifecycle must remain operator-managed")
    if concurrency != 1:
        raise VisionReviewError("local vision scheduling requires concurrency one")
    gpu_jobs = [item for item in jobs if item.get("device") == "gpu"]
    models = {str(item.get("model")) for item in gpu_jobs if item.get("model")}
    if len(models) > 1:
        raise VisionReviewError(
            "review schedule cannot start or substitute a second model"
        )
    if any(int(item.get("vramBytes") or 0) > vram_ceiling_bytes for item in gpu_jobs):
        raise VisionReviewError("GPU job exceeds the declared VRAM ceiling")
    cpu_jobs = [item for item in jobs if item.get("device") == "cpu"]
    batches: list[list[str]] = []
    if gpu_jobs:
        first = [str(gpu_jobs[0]["jobId"])]
        if "cpu-transcription" in allowed_co_residency:
            first = [str(item["jobId"]) for item in cpu_jobs] + first
            cpu_jobs = []
        batches.append(first)
        batches.extend([[str(item["jobId"])] for item in gpu_jobs[1:]])
    batches.extend([[str(item["jobId"])] for item in cpu_jobs])
    return {
        "batches": batches,
        "models": sorted(models),
        "concurrency": 1,
        "lifecycleActions": [],
    }


__all__ = [
    "VisionReviewError",
    "aggregate_finding_status",
    "build_capability_snapshot",
    "compile_context_budget",
    "compile_review_coverage",
    "fuse_protected_event_evidence",
    "review_section_pacing",
    "schedule_review_resources",
    "validate_vision_finding",
]
