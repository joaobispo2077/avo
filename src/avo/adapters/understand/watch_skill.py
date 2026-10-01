# Installed Watch Skill boundary with structured AVO review evidence.

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avo.adapters.base import JobRequest, JobResult
from avo.adapters.understand.watch_policy import (
    DEFAULT_WATCH_SETTINGS,
    build_watch_prompt,
)
from avo.timeline.ports import ToolError
from avo.timeline.vision_review import (
    VisionReviewError,
    build_capability_snapshot,
)

_BONSAI_OPTION_IDS = frozenset({"bonsai-27b-gguf", "ternary-bonsai-27b-gguf"})


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _dict_at(node: Any, key: str) -> dict[str, Any]:
    value = node.get(key) if isinstance(node, dict) else None
    return value if isinstance(value, dict) else {}


def _env_or(pin_value: Any, env_key: str) -> str:
    return str(pin_value or os.environ.get(env_key) or "").strip()


def _bonsai_paths(pin: dict[str, Any] | None) -> tuple[str, str, str]:
    source = _dict_at(pin, "source")
    companion = _dict_at(source, "companion")
    endpoint = _dict_at(source, "endpoint")
    return (
        _env_or(source.get("artifactPath"), "AVO_UNDERSTAND_GGUF"),
        _env_or(companion.get("mmproj"), "AVO_UNDERSTAND_MMPROJ"),
        _env_or(endpoint.get("baseUrl"), "WATCHSKILL_CUSTOM_BASE_URL"),
    )


def _missing_file(path: str) -> bool:
    return not path or not Path(path).is_file()


def _require_bonsai_runtime(option_id: str, pin: dict[str, Any] | None = None) -> None:
    """Fail closed when a Bonsai understand pin lacks GGUF, mmproj, or custom vision."""
    if option_id not in _BONSAI_OPTION_IDS:
        return
    gguf, mmproj, custom_url = _bonsai_paths(pin)
    if _missing_file(gguf):
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Bonsai GGUF is not ready: set AVO_UNDERSTAND_GGUF to an existing file from "
            "prism-ml/Bonsai-27B-gguf (or the ternary sibling) before Watch review.",
            True,
            "download the language GGUF, set AVO_UNDERSTAND_GGUF, then retry",
        )
    if _missing_file(mmproj):
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Watch needs the Bonsai vision mmproj alongside the language GGUF.",
            True,
            "set AVO_UNDERSTAND_MMPROJ to the vision mmproj path and retry",
        )
    cheap = (os.environ.get("WATCHSKILL_VISION_CHEAP_PROVIDER") or "").strip()
    strong = (os.environ.get("WATCHSKILL_VISION_STRONG_PROVIDER") or "").strip()
    if not custom_url and cheap != "custom" and strong != "custom":
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Bonsai understand pin only after llama.cpp custom vision is up "
            "(WATCHSKILL_CUSTOM_BASE_URL or WATCHSKILL_VISION_*_PROVIDER=custom).",
            True,
            "start llama-server with GGUF+mmproj, run watch-skill setup-vision --provider custom, then retry",
        )


def _bundled_executable() -> str | None:
    root = _repository_root()
    win = [
        root / "tools" / "watch-skill" / ".venv-win" / "Scripts" / "watch-skill.exe",
        root / "tools" / "watch-skill" / ".venv" / "Scripts" / "watch-skill.exe",
    ]
    posix = [root / "tools" / "watch-skill" / ".venv" / "bin" / "watch-skill"]
    candidates = win + posix if os.name == "nt" else posix + win
    return str(next((path for path in candidates if path.is_file()), "")) or None


_VALID_WATCH_STATUS = frozenset({"pass", "fail", "needs-human-judgment"})
_REFUSAL_MARKERS = (
    "No guess is being made",
    "does not clearly show an answer",
)


def _refusal_analysis(text: str) -> dict[str, Any] | None:
    if not any(marker in text for marker in _REFUSAL_MARKERS):
        return None
    return {
        "status": "needs-human-judgment",
        "confidence": 0.0,
        "findings": [
            {
                "classification": "meaning",
                "severity": "warning",
                "message": (
                    "Watch retrieval/vision did not produce a structured cut-proof "
                    "analysis; human must inspect the exact candidate."
                ),
                "start": None,
                "end": None,
            }
        ],
        "model": "watch-skill-refusal",
    }


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    candidates = re.findall(
        r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE
    )
    candidates.extend(text[index:] for index, char in enumerate(text) if char == "{")
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate.strip())
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def _extract_json_object(text: str) -> dict[str, Any]:
    for value in reversed(_iter_json_objects(text)):
        if str(value.get("status") or "") in _VALID_WATCH_STATUS:
            return value
    raise ValueError("Watch analysis did not return a JSON object")


@dataclass(frozen=True)
class _ReviewRequest:
    candidate: Path
    scope: str
    windows: list[dict[str, Any]]
    policy_payload: dict[str, Any]
    effective: dict[str, Any]
    artifact_dir: Path
    checkpoint: str
    context: dict[str, Any]
    prompt: str
    root: Path
    watch_env: dict[str, str]
    transcript_ref: str | Path | None
    terms: list[str]
    names: list[str]


@dataclass(frozen=True)
class _AnalysisRun:
    analysis: dict[str, Any]
    result: JobResult
    attempts: list[dict[str, Any]]


def _option_id(requested: Any) -> str:
    if requested is not None:
        return str(requested or "")
    try:
        from avo.models import resolve_option_id

        return str(resolve_option_id("understand", root=_repository_root()) or "")
    except Exception:
        return ""


def _request_value(request: dict[str, Any], key: str, default: Any) -> Any:
    return request.get(key) or default


def _policy_settings(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(request.get("policy") or {})
    configured = dict(payload.get("effective") or payload)
    return payload, {**DEFAULT_WATCH_SETTINGS, **configured}


def _artifact_directory(candidate: Path, request: dict[str, Any]) -> Path:
    default = Path(_request_value(request, "root", candidate.parent)) / ".avo-watch"
    directory = Path(_request_value(request, "artifact_dir", default))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _working_root(
    candidate: Path, request: dict[str, Any], effective: dict[str, Any]
) -> Path:
    configured = effective.get("workingDirectory")
    return Path(configured or _request_value(request, "root", candidate.parent))


def _watch_environment(
    effective: dict[str, Any], model_pin: dict[str, Any] | None = None
) -> dict[str, str]:
    environment: dict[str, str] = {}
    if effective.get("device") == "cpu":
        environment.update({"CUDA_VISIBLE_DEVICES": "-1"})
    source = _dict_at(model_pin, "source")
    endpoint = _dict_at(source, "endpoint")
    base_url = str(endpoint.get("baseUrl") or "").strip()
    served_name = str(endpoint.get("servedName") or "").strip()
    if source.get("kind") == "endpoint" and base_url and served_name:
        environment.update(
            {
                "WATCHSKILL_VISION_CHEAP_PROVIDER": "custom",
                "WATCHSKILL_VISION_CHEAP_MODEL": served_name,
                "WATCHSKILL_VISION_STRONG_PROVIDER": "custom",
                "WATCHSKILL_VISION_STRONG_MODEL": served_name,
                "WATCHSKILL_CUSTOM_BASE_URL": base_url,
            }
        )
        api_key = (os.environ.get("WATCHSKILL_CUSTOM_API_KEY") or "").strip()
        if api_key:
            environment["WATCHSKILL_CUSTOM_API_KEY"] = api_key
        elif base_url.startswith(("http://127.0.0.1", "http://localhost")):
            environment["WATCHSKILL_CUSTOM_API_KEY"] = "lm-studio"
    return environment


def _review_request(candidate: Path, request: dict[str, Any]) -> _ReviewRequest:
    scope = str(_request_value(request, "scope", "full"))
    windows = list(_request_value(request, "windows", []))
    policy_payload, effective = _policy_settings(request)
    artifact_dir = _artifact_directory(candidate, request)
    checkpoint = str(_request_value(request, "checkpoint", "cut-proof"))
    context = dict(_request_value(request, "context", {}))
    transcript_ref = request.get("transcript_ref")
    terms = list(_request_value(request, "terms", []))
    names = list(_request_value(request, "names", []))
    prompt = build_watch_prompt(
        checkpoint=checkpoint,
        scope=scope,
        windows=windows,
        context=context,
        transcript_ref=transcript_ref,
        terms=terms,
        names=names,
    )
    return _ReviewRequest(
        candidate=candidate,
        scope=scope,
        windows=windows,
        policy_payload=policy_payload,
        effective=effective,
        artifact_dir=artifact_dir,
        checkpoint=checkpoint,
        context=context,
        prompt=prompt,
        root=_working_root(candidate, request, effective),
        watch_env=_watch_environment(effective, request.get("model_pin")),
        transcript_ref=transcript_ref,
        terms=terms,
        names=names,
    )


def _window_timestamps(windows: list[dict[str, Any]]) -> list[float]:
    timestamps = {
        timestamp
        for window in windows
        for timestamp in (
            float(window["start"]),
            (float(window["start"]) + float(window["end"])) / 2,
            float(window["end"]),
        )
    }
    return sorted(timestamps)


def _watch_argv(review: _ReviewRequest) -> list[str]:
    argv = [
        "watch",
        str(review.candidate),
        review.prompt,
        "--out-dir",
        str(review.artifact_dir),
        "--index",
        "--whisper-model",
        str(review.effective["whisperModel"]),
    ]
    timestamps = _window_timestamps(review.windows)
    if timestamps:
        argv.extend(["--timestamps", ",".join(f"{value:.3f}" for value in timestamps)])
    return argv


def _acquire_candidate(adapter: Any, review: _ReviewRequest) -> tuple[JobResult, str]:
    watched = adapter.run(
        JobRequest(
            job="understand",
            label=f"Watch {review.candidate.name}",
            argv=_watch_argv(review),
            root=review.root,
            env=review.watch_env,
        )
    )
    if watched.exit_code != 0:
        raise adapter._tool_error(watched, "acquisition")
    match = re.search(r"video_id\s+`([^`]+)`", watched.stdout)
    if not match:
        raise ToolError(
            "WATCH_MALFORMED",
            "Watch acquisition did not return an indexed video id",
            True,
            "retry Watch on the exact candidate; if repeated, run watch-skill doctor",
        )
    return watched, match.group(1)


def _attempt_prompt(review: _ReviewRequest, attempt: int) -> str:
    if attempt == 1:
        return review.prompt
    return build_watch_prompt(
        checkpoint=review.checkpoint,
        scope=review.scope,
        windows=review.windows,
        context=review.context,
        transcript_ref=review.transcript_ref,
        terms=review.terms,
        names=review.names,
        repair=True,
    )


def _ask_argv(review: _ReviewRequest, video_id: str, attempt: int) -> list[str]:
    frame_key = "maxFrames" if attempt == 1 else "repairMaxFrames"
    return [
        "ask",
        video_id,
        _attempt_prompt(review, attempt),
        "--frames",
        "--no-cache",
        "--max-frames",
        str(review.effective[frame_key]),
    ]


def _attempt_record(attempt: int, result: JobResult) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "exitCode": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _analysis_from_output(text: str) -> dict[str, Any] | None:
    try:
        return _extract_json_object(text)
    except ValueError:
        return None


def _unstructured_analysis(text: str) -> dict[str, Any] | None:
    blob = text.strip()
    if not blob:
        return None
    excerpt = " ".join(blob.split())
    if len(excerpt) > 280:
        excerpt = excerpt[:277] + "..."
    return {
        "status": "needs-human-judgment",
        "confidence": 0.0,
        "findings": [
            {
                "classification": "meaning",
                "severity": "warning",
                "message": (
                    "Watch returned retrieval/vision prose instead of schema JSON "
                    f"({excerpt}); human must inspect the exact candidate."
                ),
                "start": None,
                "end": None,
            }
        ],
        "model": "watch-skill-unstructured",
    }


def _resolved_analysis(text: str) -> dict[str, Any] | None:
    return (
        _analysis_from_output(text)
        or _refusal_analysis(text)
        or _unstructured_analysis(text)
    )


def _coverage_payload(
    review: _ReviewRequest,
    attempts: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    frame_key = "maxFrames" if len(attempts) == 1 else "repairMaxFrames"
    windows = list(review.windows)
    return {
        "mode": ("full" if review.scope in {"full", "whole"} else "sampled"),
        "sampling": "frames",
        "windows": list(analysis.get("observedWindows") or []),
        "requestedScope": review.scope,
        "requestedWindows": windows,
        "requestedFrames": list(analysis.get("requestedFrames") or []),
        "decodedFrames": list(analysis.get("decodedFrames") or []),
        "failedFrames": list(analysis.get("failedFrames") or []),
        "observedFrames": list(analysis.get("observedFrames") or []),
        "inspectedRanges": list(analysis.get("inspectedRanges") or []),
        "partiallyInspectedRanges": list(
            analysis.get("partiallyInspectedRanges") or []
        ),
        "deterministicallyCheckedRanges": list(
            analysis.get("deterministicallyCheckedRanges") or []
        ),
        "coverageHoles": list(analysis.get("coverageHoles") or []),
        "maxFrames": int(review.effective[frame_key]),
    }


def _coerce_findings(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw] if raw.strip() else []
    if not isinstance(raw, list):
        return None
    findings: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            findings.append(item)
        elif isinstance(item, str):
            findings.append(
                {
                    "classification": "technical",
                    "severity": "warning",
                    "message": item,
                }
            )
        else:
            return None
    return findings


def _is_retrieval_refusal(text: str) -> bool:
    return "does not clearly show an answer" in text or "No guess is being made" in text


def _analyze_candidate(
    adapter: Any, review: _ReviewRequest, video_id: str
) -> _AnalysisRun:
    attempts: list[dict[str, Any]] = []
    latest = JobResult(exit_code=0)
    limit = int(review.effective["analysisAttempts"])
    for attempt in range(1, limit + 1):
        latest = adapter.run(
            JobRequest(
                job="understand",
                label=f"Analyze {review.candidate.name}",
                argv=_ask_argv(review, video_id, attempt),
                root=review.root,
                env=review.watch_env,
            )
        )
        attempts.append(_attempt_record(attempt, latest))
        if latest.exit_code != 0:
            raise adapter._tool_error(latest, "analysis")
        analysis = _resolved_analysis(latest.stdout)
        if analysis is None:
            continue
        if (
            attempt < limit
            and analysis.get("model")
            in {"watch-skill-unstructured", "watch-skill-refusal"}
            and _is_retrieval_refusal(latest.stdout)
        ):
            continue
        return _AnalysisRun(analysis=analysis, result=latest, attempts=attempts)
    raise ToolError(
        "WATCH_MALFORMED",
        "Watch analysis did not return a schema-valid JSON object",
        True,
        "retry the exact candidate; repeated malformed output blocks the gate",
    )


def _validated_analysis(analysis: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    status = str(analysis.get("status") or "")
    if status not in _VALID_WATCH_STATUS:
        raise ToolError(
            "WATCH_MALFORMED",
            f"invalid Watch analysis status: {status!r}",
            True,
            "retry the exact candidate with the structured-output contract",
        )
    findings = _coerce_findings(analysis.get("findings"))
    if findings is None:
        raise ToolError(
            "WATCH_MALFORMED",
            "Watch analysis findings must be a list of objects",
            True,
            "retry the exact candidate with the structured-output contract",
        )
    return status, findings


def _model_identity(result: JobResult, _analysis: dict[str, Any]) -> str | None:
    model = str(result.models_used.get("understand") or "").strip()
    return model or None


def _write_raw_artifacts(
    review: _ReviewRequest,
    watched: JobResult,
    attempts: list[dict[str, Any]],
) -> tuple[Path, Path, list[Path]]:
    raw_directory = review.artifact_dir / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    for item in attempts:
        attempt = int(item["attempt"])
        for stream in ("stdout", "stderr"):
            path = raw_directory / f"attempt-{attempt:02d}.{stream}.txt"
            path.write_text(str(item.get(stream) or ""), encoding="utf-8")
            raw_paths.append(path)
    analysis_path = review.artifact_dir / "watch-analysis.txt"
    analysis_path.write_text(
        "\n\n".join(
            f"--- attempt {item['attempt']} stdout ---\n{item['stdout']}\n"
            f"--- attempt {item['attempt']} stderr ---\n{item['stderr']}"
            for item in attempts
        ),
        encoding="utf-8",
    )
    report_path = review.artifact_dir / "watch-report.md"
    report_path.write_text(watched.stdout, encoding="utf-8")
    raw_paths.extend(path for path in watched.artifact_paths if Path(path).is_file())
    return report_path, analysis_path, raw_paths


def _raw_artifact_ref(path: Path, *, kind: str) -> dict[str, Any]:
    data = Path(path).read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
        "kind": kind,
    }


def _evidence_payload(
    adapter: Any,
    review: _ReviewRequest,
    analysis_run: _AnalysisRun,
    report_path: Path,
    analysis_path: Path,
    raw_paths: list[Path],
) -> dict[str, Any]:
    status, findings = _validated_analysis(analysis_run.analysis)
    external_paths = [
        *analysis_run.result.artifact_paths,
    ]
    raw_refs = [
        _raw_artifact_ref(path, kind="watch-raw")
        for path in [report_path, analysis_path, *raw_paths, *external_paths]
        if Path(path).is_file()
    ]
    attempts = [
        {
            "attempt": int(item["attempt"]),
            "exitCode": int(item["exitCode"]),
            "stdoutSha256": hashlib.sha256(
                str(item.get("stdout") or "").encode("utf-8")
            ).hexdigest(),
            "stderrSha256": hashlib.sha256(
                str(item.get("stderr") or "").encode("utf-8")
            ).hexdigest(),
        }
        for item in analysis_run.attempts
    ]
    return {
        "schemaVersion": "1.0.0",
        "status": status,
        "checkpoint": review.checkpoint,
        "candidate": str(review.candidate),
        "coverage": _coverage_payload(
            review, analysis_run.attempts, analysis_run.analysis
        ),
        "findings": findings,
        "confidence": analysis_run.analysis.get("confidence"),
        "tool": "watch-skill",
        "toolVersion": adapter.tool_version(),
        "model": _model_identity(analysis_run.result, analysis_run.analysis),
        "outcomeKind": (
            "uncertainty" if status == "needs-human-judgment" else "content"
        ),
        "policy": {
            "effective": review.effective,
            "sources": dict(review.policy_payload.get("sources") or {}),
            "policyHash": review.policy_payload.get("policyHash"),
        },
        "reviewContext": review.context,
        "promptSha256": hashlib.sha256(review.prompt.encode("utf-8")).hexdigest(),
        "attempts": attempts,
        "rawArtifactRefs": raw_refs,
    }


def _write_evidence(review: _ReviewRequest, payload: dict[str, Any]) -> Path:
    evidence_path = review.artifact_dir / "watch-evidence.json"
    evidence_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence_path


def probe_vision_capabilities(
    *,
    model_pin: dict[str, Any],
    probe: Callable[[str, str], dict[str, Any]],
    resource_policy: dict[str, Any],
    conservative_context_limit: int | None = None,
) -> dict[str, Any]:
    """Probe the exact configured OpenAI-compatible endpoint and freeze identity."""
    source = _dict_at(model_pin, "source")
    endpoint = _dict_at(source, "endpoint")
    configured_model = str(model_pin.get("id") or "").strip()
    served_name = str(endpoint.get("servedName") or "").strip()
    base_url = str(endpoint.get("baseUrl") or "").strip()
    if (
        source.get("kind") != "endpoint"
        or not configured_model
        or not served_name
        or not base_url
    ):
        raise VisionReviewError("vision review requires an exact endpoint model pin")
    if served_name != configured_model:
        raise VisionReviewError("configured model pin and endpoint served name differ")
    try:
        observed = probe(base_url, served_name)
    except Exception as error:
        raise VisionReviewError(
            f"vision endpoint live probe failed: {error}"
        ) from error
    return build_capability_snapshot(
        configured_model=configured_model,
        endpoint_identity={
            "providerType": "openai-compatible",
            "redactedBase": re.sub(r"//[^/]+", "//<endpoint>", base_url),
        },
        probe=observed,
        resource_policy=resource_policy,
        conservative_context_limit=conservative_context_limit,
    )


def _retry_reduction(
    review_pass: dict[str, Any], retry_number: int
) -> tuple[dict[str, Any], str]:
    reduced = deepcopy(review_pass)
    frames = list(reduced.get("sampleFrames") or [])
    deduplicated = list(dict.fromkeys(frames))
    if deduplicated != frames:
        reduced["sampleFrames"] = deduplicated
        reduction = "deduplicate-frames"
    elif reduced.get("detail") not in {None, "low"}:
        reduced["detail"] = "low"
        reduction = "reduce-detail"
    elif int(reduced.get("transcriptHandleFrames") or 0) > 0:
        reduced["transcriptHandleFrames"] = max(
            0, int(reduced.get("transcriptHandleFrames") or 0) // 2
        )
        reduction = "reduce-transcript-handles"
    else:
        midpoint = max(1, len(frames) // 2)
        reduced["windowSegments"] = [frames[:midpoint], frames[midpoint:]]
        reduction = "split-window"
    required = set(review_pass.get("requiredFrames") or [])
    if not required.issubset(set(reduced.get("sampleFrames") or [])):
        raise VisionReviewError("bounded retry would drop mandatory coverage")
    return reduced, reduction


def execute_bounded_passes(
    *,
    candidate_index: str,
    passes: list[dict[str, Any]],
    capability_snapshot: dict[str, Any],
    invoke: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute bounded passes against one index and one verified served model."""
    expected_model = str(capability_snapshot.get("servedModel") or "")
    if not candidate_index or not expected_model:
        raise VisionReviewError(
            "candidate index and verified served model are required"
        )
    pass_results: list[dict[str, Any]] = []
    requested: list[int] = []
    decoded: list[int] = []
    failed: list[int] = []
    observed: list[int] = []
    for original in passes:
        current = deepcopy(original)
        max_attempts = max(1, int(current.get("maxAttempts") or 1))
        retry_history: list[dict[str, Any]] = []
        response: dict[str, Any] = {}
        for attempt in range(1, max_attempts + 1):
            response = invoke(candidate_index, deepcopy(current))
            response_model = str(response.get("model") or "")
            if response_model != expected_model:
                raise VisionReviewError(
                    f"review model {response_model!r} does not match verified model {expected_model!r}"
                )
            response_identity = response.get("capabilityIdentityHash")
            if (
                response_identity is not None
                and response_identity != capability_snapshot.get("identityHash")
            ):
                raise VisionReviewError(
                    "review endpoint capability identity changed during execution"
                )
            if response.get("lifecycleActions"):
                raise VisionReviewError(
                    "review attempted to manage the operator-owned model lifecycle"
                )
            if response.get("status") in {"pass", "fail", "needs-human-judgment"}:
                required_fields = {
                    "requestedFrames",
                    "decodedFrames",
                    "failedFrames",
                    "observedFrames",
                }
                if required_fields.issubset(response):
                    break
                response = {**response, "status": "malformed"}
            if attempt == max_attempts:
                response = {
                    **response,
                    "status": "blocked",
                    "requestedFrames": list(current.get("sampleFrames") or []),
                    "decodedFrames": [],
                    "failedFrames": list(current.get("sampleFrames") or []),
                    "observedFrames": [],
                }
                break
            current, reduction = _retry_reduction(current, attempt)
            retry_history.append(
                {
                    "attempt": attempt,
                    "trigger": response.get("status") or "malformed",
                    "reduction": reduction,
                }
            )
        requested.extend(int(frame) for frame in response["requestedFrames"])
        decoded.extend(int(frame) for frame in response["decodedFrames"])
        failed.extend(int(frame) for frame in response["failedFrames"])
        observed.extend(int(frame) for frame in response["observedFrames"])
        pass_results.append(
            {
                "passId": original["passId"],
                "status": response["status"],
                "requestedFrames": list(response["requestedFrames"]),
                "decodedFrames": list(response["decodedFrames"]),
                "failedFrames": list(response["failedFrames"]),
                "observedFrames": list(response["observedFrames"]),
                "findings": deepcopy(response.get("findings") or []),
                "retryHistory": retry_history,
                "rawArtifactRefs": deepcopy(response.get("rawArtifactRefs") or []),
            }
        )
    return {
        "candidateIndex": candidate_index,
        "model": expected_model,
        "capabilityIdentityHash": capability_snapshot.get("identityHash"),
        "passResults": pass_results,
        "requestedSamples": list(dict.fromkeys(requested)),
        "decodedSamples": list(dict.fromkeys(decoded)),
        "failedSamples": list(dict.fromkeys(failed)),
        "observedSamples": list(dict.fromkeys(observed)),
    }


class WatchSkillAdapter:
    routing_id = "watch-skill"

    def __init__(self, executable: str | None = None):
        self.executable = (
            executable
            or os.environ.get("WATCH_SKILL_BIN")
            or _bundled_executable()
            or shutil.which("watch-skill")
            or "watch-skill"
        )

    @staticmethod
    def validate_coverage(scope: str, windows: list[dict[str, Any]]) -> None:
        if scope in {"targeted", "windows"} and not windows:
            raise ValueError("targeted Watch review requires changed/risk windows")

    def run(self, request: JobRequest) -> JobResult:
        environment = os.environ.copy()
        environment.update(request.env)
        try:
            completed = subprocess.run(
                [self.executable, *request.argv],
                cwd=request.root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as error:
            return JobResult(exit_code=2, stderr=f"watch-skill unavailable: {error}")
        stdout = completed.stdout or ""
        artifacts = [
            Path(line.strip())
            for line in stdout.splitlines()
            if line.strip().endswith((".json", ".md", ".html"))
            and Path(line.strip()).exists()
        ]
        models_used: dict[str, str] = {}
        model_sources: dict[str, Any] = {}
        try:
            from avo.model_sources import (
                disclosure_for,
                invocation_from_env,
                resolve_job,
            )

            resolved = resolve_job(
                "understand",
                root=request.root,
                invocation=invocation_from_env(environment),
            )
            if resolved.id:
                models_used = {"understand": resolved.catalog_label or resolved.id}
                model_sources = {"understand": disclosure_for(resolved)}
        except Exception:
            pass
        return JobResult(
            exit_code=completed.returncode,
            artifact_paths=artifacts,
            stdout=stdout,
            stderr=completed.stderr or "",
            models_used=models_used,
            model_sources=model_sources,
        )

    def tool_version(self) -> str:
        result = self.run(
            JobRequest(
                job="understand",
                label="Watch version",
                argv=["version"],
                root=_repository_root(),
            )
        )
        return (
            result.stdout.strip().splitlines()[0]
            if result.exit_code == 0 and result.stdout.strip()
            else "unknown"
        )

    @staticmethod
    def _tool_error(result: JobResult, phase: str) -> ToolError:
        return ToolError(
            "WATCH_UNAVAILABLE",
            result.stderr or result.stdout or f"Watch {phase} failed",
            True,
            "run watch-skill doctor, repair the local tool/model, and retry the same candidate",
        )

    def review(self, candidate: Path, **request: Any) -> dict[str, Any]:
        candidate = Path(candidate)
        self.validate_coverage(
            str(_request_value(request, "scope", "full")),
            list(_request_value(request, "windows", [])),
        )
        option_id = _option_id(request.get("option_id"))
        pin = request.get("model_pin")
        if not isinstance(pin, dict):
            pin = None
            try:
                from avo.model_sources import invocation_from_env, resolve_job

                resolved = resolve_job(
                    "understand",
                    root=_repository_root(),
                    invocation=invocation_from_env(os.environ),
                )
                if resolved.id == option_id:
                    pin = resolved.pin
            except Exception:
                pin = None
        _require_bonsai_runtime(option_id, pin=pin)
        review = _review_request(candidate, request)
        watched, video_id = _acquire_candidate(self, review)
        analysis_run = _analyze_candidate(self, review, video_id)
        report_path, analysis_path, raw_paths = _write_raw_artifacts(
            review, watched, analysis_run.attempts
        )
        payload = _evidence_payload(
            self, review, analysis_run, report_path, analysis_path, raw_paths
        )
        evidence_path = _write_evidence(review, payload)
        return {
            **payload,
            "artifacts": [
                str(report_path),
                str(analysis_path),
                *[str(path) for path in raw_paths],
                str(evidence_path),
                *[
                    str(path)
                    for path in watched.artifact_paths
                    + analysis_run.result.artifact_paths
                ],
            ],
        }
