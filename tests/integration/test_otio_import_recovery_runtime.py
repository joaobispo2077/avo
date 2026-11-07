"""Native originals survive interruption, explicit re-import, and canonical return."""

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from tests.integration.test_code_drawn_canonical_pipeline import _pixels
from tests.integration.test_otio_import_runtime import _native_trial, _render_import

from avo.timeline import import_service
from avo.timeline import store as storage
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_evidence import verify_import_origin
from avo.timeline.lifecycle import PipelineRunStore
from avo.timeline.otio_import import ImportError

pytestmark = pytest.mark.integration
CASES = [
    "prepare-interrupted",
    "intent-before",
    "intent-after",
    "index-before",
    "index-after",
    "lifecycle-after",
    "receipt-after",
    "source-before",
    "source-after",
    "head-conflict",
    "idempotent-retry",
    "return",
]


def _stage(service):
    origin = service.status()["currentOrigin"]
    session = service.load(origin["importId"])
    document = json.loads(
        (service.root / session["importId"] / "source.otio").read_text()
    )
    document["tracks"]["children"][0]["children"][0]["source_range"]["start_time"][
        "value"
    ] += 1
    export = service.workspace.raw_dir / "revised.otio"
    export.write_text(json.dumps(document))
    prepared = service.prepare(
        export,
        mappings=session["options"]["mappings"],
        declarations=session["options"]["declarations"],
        actor="native-fixture",
        reason="Explicit source-linked replacement",
    )
    ready = service.validate(prepared["importId"])
    assert ready["status"] == "ready-to-activate", ready["findings"]
    return ready


def _select(service, ready):
    return service.activate(
        ready["importId"],
        validation_hash=ready["validationHash"],
        expected_head=ready["validation"]["locks"]["expectedHeadHash"],
        actor="native-fixture",
        reason="Select reviewed synthetic replacement",
    )


def _patch_failure(patch, service, case, source, initial_id):
    if case.startswith("intent"):
        real = import_service.write_immutable_json

        def intent(path, value):
            selected = Path(path).parent.name == "activation"
            if selected and case.endswith("before"):
                raise OSError("native fixture before intent")
            result = real(path, value)
            if selected:
                raise OSError("native fixture after intent")
            return result

        patch.setattr(import_service, "write_immutable_json", intent)
    elif case.startswith("index") or case == "source-after":
        real = storage.atomic_write_json

        def index(path, value):
            selected = (
                Path(path) == service.workspace.artifact_path("cmap")
                and value.get("headRevisionId") != initial_id
            )
            if selected and case.endswith("before"):
                raise OSError("native fixture before selection")
            result = real(path, value)
            if selected:
                if case == "source-after":
                    source.write_bytes(b"changed after native canonical commit")
                else:
                    raise OSError("native fixture after selection")
            return result

        patch.setattr(storage, "atomic_write_json", index)
    elif case == "receipt-after":
        real = service._record

        def record(import_id, category, value):
            result = real(import_id, category, value)
            if category == "activation-results":
                raise OSError("native fixture after reconciliation evidence")
            return result

        patch.setattr(service, "_record", record)
    elif case == "lifecycle-after":
        real = PipelineRunStore._write

        def lifecycle(run, value, **kwargs):
            result = real(run, value, **kwargs)
            if (
                value["mainState"] == "cmap-draft"
                and value["activeRefs"].get("cmapRevisionId") != initial_id
            ):
                raise OSError("native fixture after lifecycle selection")
            return result

        patch.setattr(PipelineRunStore, "_write", lifecycle)


@pytest.mark.parametrize("case", CASES)
def test_native_recovery_exercises(tmp_path, monkeypatch, case):
    service, source = _native_trial(tmp_path)
    store = service.workspace.store("cmap")
    initial = store.revision(store.load_index()["headRevisionId"])
    original_bytes = source.read_bytes()
    fingerprint = file_fingerprint(source)["sha256"]
    if case == "prepare-interrupted":
        real = import_service._immutable_bytes

        def interrupted(path, value):
            real(path, value)
            raise OSError("native fixture cancelled preparation")

        with monkeypatch.context() as patch:
            patch.setattr(import_service, "_immutable_bytes", interrupted)
            with pytest.raises(ImportError):
                _stage(service)
        assert service.head_hash() == initial["contentHash"]
        storage.require_reconciled(service.workspace.timeline_dir)
    ready = _stage(service)
    expected_count = 2
    if case == "head-conflict":
        snapshot = deepcopy(initial["snapshot"])
        snapshot["segments"][1]["in"]["ticks"] += 1
        later = CMapService(service.workspace).author(
            snapshot, actor="native-fixture", reason="Concurrent requested trim"
        )
        with pytest.raises(ImportError):
            _select(service, ready)
        assert service.head_hash() == later["contentHash"]
        ready = service.validate(ready["importId"])
        expected_count = 3
    elif case == "source-before":
        source.write_bytes(b"changed between validation and native selection")
        with pytest.raises(ImportError):
            _select(service, ready)
        assert service.head_hash() == initial["contentHash"]
        source.write_bytes(original_bytes)
    elif case not in {"prepare-interrupted", "idempotent-retry", "return"}:
        with monkeypatch.context() as patch:
            _patch_failure(patch, service, case, source, initial["revisionId"])
            with pytest.raises(ImportError):
                _select(service, ready)
        if case == "source-after":
            assert service._pending_path().exists()
            source.write_bytes(original_bytes)
    selected = _select(service, ready)["revision"]
    if case == "return":
        options = {
            "expected_head": selected["contentHash"],
            "actor": "native-fixture",
            "reason": "Return prior synthetic edit",
        }
        service.rollback(selected["snapshot"]["originRef"]["activationId"], **options)
        service.rollback(selected["snapshot"]["originRef"]["activationId"], **options)
        expected_count = 3
    else:
        _select(service, ready)
    current = store.revision(store.load_index()["headRevisionId"])
    assert len(store.load_index()["revisionRefs"]) == expected_count
    assert store.revision(initial["revisionId"])["snapshot"] == initial["snapshot"]
    assert store.effective_approval() is None
    assert verify_import_origin(service.workspace, current)
    storage.require_reconciled(service.workspace.timeline_dir)
    assert file_fingerprint(source)["sha256"] == fingerprint
    if case in {"index-after", "return"}:
        output = _render_import(service, case)
        frames = _pixels(source)
        intervals = [(12, 24), (48, 60)] if case == "return" else [(13, 25), (48, 60)]
        assert np.array_equal(
            _pixels(output), np.concatenate([frames[a:b] for a, b in intervals])
        )
