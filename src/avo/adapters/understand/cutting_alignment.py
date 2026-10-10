"""Serialized, explicitly provisioned offline CPU character alignment."""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from threading import Lock

from avo.timeline.ports import ToolError
from avo.transcribe import source_fingerprint


def _aligned_time(item):
    first, last = item.get("start"), item.get("end")
    return (
        isinstance(first, (float, int))
        and isinstance(last, (float, int))
        and math.isfinite(first)
        and math.isfinite(last)
        and last > first
    )


def _mapped(item, source_start, eligible):
    return {
        **item,
        "start": None if item.get("start") is None else item["start"] + source_start,
        "end": None if item.get("end") is None else item["end"] + source_start,
        "eligibleEdge": eligible,
        "alignmentStatus": "aligned" if eligible else "unsupported",
    }


def _char_eligible(char, dictionary):
    return (
        char.get("char", "").lower() in dictionary
        and _aligned_time(char)
        and char.get("score", 0) >= 0.5
    )


def _within_word(char, word):
    return (
        _aligned_time(char)
        and _aligned_time(word)
        and char["start"] >= word["start"]
        and char["end"] <= word["end"]
        and char.get("char", "").isalnum()
    )


def _word_eligible(word, characters, dictionary):
    letters = _word_letters(word)
    observed = [char for char in characters if _within_word(char, word)]
    return (
        _supported_letters(letters, dictionary)
        and _aligned_time(word)
        and [char["char"].lower() for char in observed] == letters
        and all(char.get("score", 0) >= 0.5 for char in observed)
    )


def _word_letters(word):
    return [char.lower() for char in word.get("word", "") if char.isalnum()]


def _supported_letters(letters, dictionary):
    return bool(letters) and all(char in dictionary for char in letters)


def normalize_alignment(raw, *, dictionary, source_start=0.0):
    words, chars = [], []
    for segment in raw.get("segments", []):
        characters = segment.get("chars") or []
        chars.extend(
            _mapped(char, source_start, _char_eligible(char, dictionary))
            for char in characters
        )
        for word in segment.get("words") or []:
            words.append(
                {
                    **_mapped(
                        word, source_start, _word_eligible(word, characters, dictionary)
                    ),
                    "text": word.get("word", ""),
                }
            )
    return {"words": words, "chars": chars, "interpolated": False}


def _verify_model_manifest(model):
    if not model or not model.get("files"):
        raise ToolError(
            "cutting-alignment-model", "local model file manifest is required"
        )
    directory = Path(model["path"]).resolve()
    for locator, expected in model["files"].items():
        artifact = (directory / locator).resolve()
        if not artifact.is_relative_to(directory) or not artifact.is_file():
            raise ToolError(
                "cutting-alignment-model", "local model artifact is missing or unsafe"
            )
        if source_fingerprint(artifact)["sha256"] != expected:
            raise ToolError(
                "cutting-alignment-model", "local model fingerprint mismatch"
            )
    return directory


class CuttingAlignmentAdapter:
    def __init__(
        self, python: Path, models: dict, *, nltk_data: Path | None = None, timeout=120
    ):
        self.python = Path(python)
        self.models = models
        self.nltk_data = Path(nltk_data) if nltk_data else None
        self.timeout = timeout
        self._lock = Lock()

    def _preflight(self, language):
        key = language.lower().split("-")[0]
        if key not in {"pt", "en"}:
            raise ToolError(
                "cutting-alignment-language", "alignment language is not validated"
            )
        if not self.python.is_file():
            raise ToolError(
                "cutting-alignment-runtime", "optional runtime is not provisioned"
            )
        model = self.models.get(key)
        directory = _verify_model_manifest(model)
        resource = "portuguese" if key == "pt" else "english"
        if (
            self.nltk_data is None
            or not (self.nltk_data / "tokenizers" / "punkt_tab" / resource).is_dir()
        ):
            raise ToolError(
                "cutting-alignment-punkt", "explicit local Punkt resources are missing"
            )
        return key, directory, model

    def align(self, source, **request):
        language, directory, model = self._preflight(request.get("language", "pt-BR"))
        payload = {
            "audioPath": str(Path(source).resolve()),
            "language": language,
            "modelPath": str(directory),
            "nltkData": str(self.nltk_data.resolve()),
            "segments": request.get("segments", []),
            "expectedVersion": "3.8.6",
        }
        environment = {
            **os.environ,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "NLTK_DATA": payload["nltkData"],
            "CUDA_VISIBLE_DEVICES": "",
            "PYTHONNOUSERSITE": "1",
        }
        worker = Path(__file__).with_name("cutting_alignment_worker.py")
        try:
            with self._lock:
                result = subprocess.run(
                    [str(self.python), "-I", str(worker)],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    timeout=self.timeout,
                    env=environment,
                    check=True,
                )
            output = json.loads(result.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
            raise ToolError(
                "cutting-alignment-worker", f"offline alignment failed: {exc}"
            ) from exc
        evidence = normalize_alignment(
            output["raw"],
            dictionary=output["dictionary"],
            source_start=request.get("source_start", 0.0),
        )
        return {
            **evidence,
            "bindings": {
                "engine": "whisperx",
                "version": "3.8.6",
                "device": "cpu",
                "modelFiles": model["files"],
                "language": language,
            },
            "observed": True,
        }
