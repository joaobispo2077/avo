from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avo.model_sources import (
    PreflightError,
    disclosure_for,
    normalize_pin,
    pin_from_document,
    preflight,
    redact_endpoint,
    resolve_job,
)
from avo.paths import schema_path
from avo.transcribe import MODEL_FILES
from jsonschema_support import validator_for

ROOT = Path(__file__).resolve().parents[1]


def _empty_state() -> dict:
    return {"models": {}, "transcription": {}, "videos": {}}


class ModelSourceUnitTests(unittest.TestCase):
    def test_stronger_full_pin_keeps_source_and_runtime_over_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_path = root / "global-small"
            state_path = root / "state-large"
            global_config = {
                "models": {
                    "transcribe": {
                        "default": "small",
                        "source": {
                            "kind": "artifact",
                            "artifactPath": str(global_path),
                        },
                        "runtime": {"device": "cpu", "computeType": "int8"},
                    }
                }
            }
            state = {
                "models": {
                    "transcribe": {
                        "id": "large-v3",
                        "source": {
                            "kind": "artifact",
                            "artifactPath": str(state_path),
                        },
                        "runtime": {"device": "cuda", "computeType": "float16"},
                    }
                }
            }
            with mock.patch("avo.models.load_config", return_value=global_config):
                resolved = resolve_job(
                    "transcribe",
                    root=ROOT,
                    state=state,
                    provider={},
                    registry={},
                )

        self.assertEqual(resolved.id, "large-v3")
        self.assertEqual(
            resolved.pin["source"]["artifactPath"], str(state_path.resolve())
        )
        self.assertEqual(resolved.pin["runtime"]["device"], "cuda")
        self.assertEqual(resolved.sources["source"], "state")
        self.assertEqual(resolved.sources["runtime"], "state")

    def test_normalize_pin_string_and_default_alias(self) -> None:
        self.assertEqual(normalize_pin("medium"), {"id": "medium"})
        self.assertEqual(normalize_pin({"default": "small"}), {"id": "small"})

    def test_same_file_models_transcribe_beats_alias(self) -> None:
        pin = pin_from_document(
            {
                "transcription": {"model": "small"},
                "models": {"transcribe": {"id": "large-v3"}},
            },
            "transcribe",
        )
        self.assertEqual(pin, {"id": "large-v3"})

    def test_project_beats_provider(self) -> None:
        with mock.patch("avo.models.avo_state.load_state", return_value=_empty_state()):
            resolved = resolve_job(
                "understand",
                root=ROOT,
                project={"models": {"understand": "bonsai-27b-gguf"}},
                provider={"models": {"understand": "qwen2.5-7b"}},
                state=_empty_state(),
                hardware_tier=None,
            )
        self.assertEqual(resolved.id, "bonsai-27b-gguf")
        self.assertEqual(resolved.sources.get("id"), "project")

    def test_state_scope_is_not_global(self) -> None:
        state = {"transcription": {"model": "medium"}, "models": {}, "videos": {}}
        resolved = resolve_job(
            "transcribe",
            root=ROOT,
            project={},
            state=state,
            hardware_tier=None,
        )
        self.assertEqual(resolved.id, "medium")
        self.assertEqual(resolved.sources.get("id"), "state")

    def test_project_wins_over_video_state(self) -> None:
        state = {
            "models": {},
            "transcription": {},
            "videos": {"bishop:demo": {"transcription": {"model": "base"}}},
        }
        resolved = resolve_job(
            "transcribe",
            root=ROOT,
            project={"transcription": {"model": "medium"}},
            state=state,
            video_key="bishop:demo",
            hardware_tier=None,
        )
        self.assertEqual(resolved.id, "medium")
        self.assertEqual(resolved.sources.get("id"), "project")

    def test_id_only_project_clears_provider_artifact(self) -> None:
        provider = {
            "models": {
                "transcribe": {
                    "id": "large-v3",
                    "source": {
                        "kind": "artifact",
                        "artifactPath": "D:/weights/large-v3",
                    },
                }
            }
        }
        resolved = resolve_job(
            "transcribe",
            root=ROOT,
            project={"transcription": {"model": "medium"}},
            provider=provider,
            state=_empty_state(),
            hardware_tier=None,
        )
        self.assertEqual(resolved.id, "medium")
        artifact = (resolved.pin.get("source") or {}).get("artifactPath", "")
        self.assertNotIn("large-v3", artifact.replace("\\", "/"))
        self.assertTrue(str(artifact).replace("\\", "/").endswith("/medium"))

    def test_hardware_does_not_override_state_id(self) -> None:
        resolved = resolve_job(
            "transcribe",
            root=ROOT,
            state={"transcription": {"model": "medium"}},
            hardware_tier={"whisper": "tiny"},
        )
        self.assertEqual(resolved.id, "medium")
        self.assertEqual(resolved.sources.get("id"), "state")

    def test_hardware_may_replace_catalog_id(self) -> None:
        resolved = resolve_job(
            "transcribe",
            root=ROOT,
            state=_empty_state(),
            hardware_tier={"whisper": "base"},
        )
        self.assertEqual(resolved.id, "base")
        self.assertEqual(resolved.sources.get("id"), "hardware")

    def test_redact_endpoint_strips_userinfo_and_secrets(self) -> None:
        url = "https://user:hunter2@127.0.0.1:8080/v1?api_key=secret&ok=1"
        redacted = redact_endpoint(url)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("user:", redacted)
        self.assertIn("***", redacted)
        self.assertIn("ok=1", redacted)

    def test_disclosure_omits_raw_endpoint_secret(self) -> None:
        resolved = resolve_job(
            "understand",
            root=ROOT,
            state=_empty_state(),
            invocation={
                "id": "qwen2.5-7b",
                "source": {
                    "kind": "endpoint",
                    "endpoint": {
                        "baseUrl": "http://token:x@127.0.0.1:9/v1?api_key=leak",
                        "servedName": "local",
                    },
                },
            },
            hardware_tier=None,
        )
        payload = disclosure_for(resolved)
        blob = json.dumps(payload)
        self.assertNotIn("leak", blob)
        self.assertNotIn("token:", blob)

    def test_explicit_unsupported_compute_fails_closed(self) -> None:
        resolved = resolve_job(
            "transcribe",
            root=ROOT,
            project={
                "models": {
                    "transcribe": {
                        "id": "small",
                        "runtime": {"device": "cpu", "computeType": "float16"},
                    }
                }
            },
            state=_empty_state(),
            hardware_tier=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "small"
            model_dir.mkdir()
            for name in MODEL_FILES:
                (model_dir / name).write_text("{}", encoding="utf-8")
            resolved.pin.setdefault("source", {})["kind"] = "artifact"
            resolved.pin["source"]["artifactPath"] = str(model_dir)
            with self.assertRaises(PreflightError) as raised:
                preflight(
                    resolved,
                    supported_compute_types=lambda _device: frozenset({"int8"}),
                )
        self.assertEqual(raised.exception.code, "incompatible_runtime")

    def test_offline_existing_artifact_reuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "small"
            model_dir.mkdir()
            for name in MODEL_FILES:
                (model_dir / name).write_text("{}", encoding="utf-8")
            resolved = resolve_job(
                "transcribe",
                root=ROOT,
                project={
                    "rawDir": tmp,
                    "models": {
                        "transcribe": {
                            "id": "small",
                            "source": {
                                "kind": "artifact",
                                "artifactPath": str(model_dir),
                            },
                            "runtime": {"offline": True, "allowDownload": False},
                        }
                    },
                },
                state=_empty_state(),
                hardware_tier=None,
            )
            preflight(
                resolved, supported_compute_types=lambda _d: frozenset({"int8", "auto"})
            )
            self.assertEqual(disclosure_for(resolved)["reuse"], "existing")

    def test_download_disallowed_when_unprepared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-prepared" / "small"
            resolved = resolve_job(
                "transcribe",
                root=ROOT,
                project={
                    "models": {
                        "transcribe": {
                            "id": "small",
                            "source": {
                                "kind": "artifact",
                                "artifactPath": str(missing),
                            },
                            "runtime": {"offline": True, "allowDownload": False},
                        }
                    }
                },
                state=_empty_state(),
                hardware_tier=None,
            )
            with self.assertRaises(PreflightError) as raised:
                preflight(resolved)
        self.assertEqual(raised.exception.code, "missing_artifact")

    def test_inferred_offline_path_is_download_disallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "models"
            with mock.patch("avo.model_sources.default_model_root", return_value=cache):
                resolved = resolve_job(
                    "transcribe",
                    root=ROOT,
                    state=_empty_state(),
                    hardware_tier=None,
                )
                with self.assertRaises(PreflightError) as raised:
                    preflight(resolved)
        self.assertEqual(raised.exception.code, "download_disallowed")

    def test_secret_env_missing(self) -> None:
        resolved = resolve_job(
            "understand",
            root=ROOT,
            state=_empty_state(),
            invocation={
                "id": "qwen2.5-7b",
                "source": {
                    "kind": "endpoint",
                    "endpoint": {
                        "baseUrl": "http://127.0.0.1:9/v1",
                        "apiKeyEnv": "WATCHSKILL_API_KEY",
                    },
                },
            },
            hardware_tier=None,
        )
        with self.assertRaises(PreflightError) as raised:
            preflight(
                resolved,
                http_get=lambda _url: (200, '{"data":[{"id":"qwen2.5-7b"}]}'),
                getenv=lambda _name: None,
            )
        self.assertEqual(raised.exception.code, "secret_env_missing")
        self.assertIn("WATCHSKILL_API_KEY", str(raised.exception))

    def test_served_name_mismatch_and_unreachable(self) -> None:
        resolved = resolve_job(
            "understand",
            root=ROOT,
            state=_empty_state(),
            invocation={
                "id": "qwen2.5-7b",
                "source": {
                    "kind": "endpoint",
                    "endpoint": {
                        "baseUrl": "http://127.0.0.1:9/v1",
                        "servedName": "bonsai-27b",
                    },
                },
            },
            hardware_tier=None,
        )
        with self.assertRaises(PreflightError) as raised:
            preflight(
                resolved,
                http_get=lambda _url: (200, '{"data":[{"id":"other"}]}'),
            )
        self.assertEqual(raised.exception.code, "served_name_mismatch")

        with self.assertRaises(PreflightError) as raised:
            preflight(
                resolved, http_get=lambda _url: (_ for _ in ()).throw(OSError("nope"))
            )
        self.assertEqual(raised.exception.code, "unreachable_endpoint")

    def test_incomplete_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "hub"
            cache.mkdir()
            resolved = resolve_job(
                "transcribe",
                root=ROOT,
                project={
                    "models": {
                        "transcribe": {
                            "id": "small",
                            "source": {"kind": "hf-cache", "cacheDir": str(cache)},
                        }
                    }
                },
                state=_empty_state(),
                hardware_tier=None,
            )
            with self.assertRaises(PreflightError) as raised:
                preflight(resolved, snapshot_complete=lambda _path: False)
            self.assertEqual(raised.exception.code, "incomplete_snapshot")

    def test_relative_artifact_resolves_against_raw_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolved = resolve_job(
                "transcribe",
                root=ROOT,
                project={
                    "rawDir": tmp,
                    "models": {
                        "transcribe": {
                            "id": "small",
                            "source": {
                                "kind": "artifact",
                                "artifactPath": "weights/small",
                            },
                        }
                    },
                },
                state=_empty_state(),
                hardware_tier=None,
            )
        artifact = Path(resolved.pin["source"]["artifactPath"])
        self.assertEqual(artifact, (Path(tmp) / "weights" / "small").resolve())


class ModelSourceSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            schema_path("avo.project.schema.json").read_text(encoding="utf-8")
        )
        self.validator = validator_for(self.schema)
        self.base = {"provider": "bishop", "rawDir": "/media/raw"}

    def test_project_accepts_model_pin_object(self) -> None:
        document = {
            **self.base,
            "models": {
                "transcribe": {
                    "id": "medium",
                    "source": {"kind": "artifact", "artifactPath": "D:/models/medium"},
                    "runtime": {
                        "device": "cpu",
                        "computeType": "int8",
                        "offline": True,
                    },
                }
            },
        }
        self.assertEqual(list(self.validator.iter_errors(document)), [])

    def test_project_rejects_api_key_in_endpoint(self) -> None:
        document = {
            **self.base,
            "models": {
                "understand": {
                    "id": "qwen2.5-7b",
                    "source": {
                        "kind": "endpoint",
                        "endpoint": {
                            "baseUrl": "http://127.0.0.1:8080/v1",
                            "apiKey": "sk-leak",
                        },
                    },
                }
            },
        }
        errors = list(self.validator.iter_errors(document))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
