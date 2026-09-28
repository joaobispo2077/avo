from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.timeline.component_instances import (
    ComponentInstanceError,
    ComponentInstanceService,
)
from avo.timeline.contracts import file_fingerprint

HASH_A = "a" * 64
HASH_B = "b" * 64


def _workspace(tmp_path):
    return SimpleNamespace(
        timeline_dir=tmp_path / "edit" / "timeline",
        raw_dir=tmp_path,
    )


def _instance(path):
    fingerprint = file_fingerprint(path)
    return {
        "instanceId": "instance-lower-third",
        "kitId": "kit-lower-third",
        "kitVersion": "1.2.0",
        "kitManifestHash": HASH_A,
        "parameters": {"handle": "@bishopnosekai"},
        "assetBindings": [],
        "eventBindings": [
            {"slot": "entry", "eventId": "event-entry", "revisionHash": HASH_B}
        ],
        "safeAreaBindings": {"faces": [], "captions": [], "evidence": [], "ui": []},
        "generatedFiles": [{"path": str(path), "sha256": fingerprint["sha256"]}],
        "reviewRefs": [
            {"kind": "accessibility", "sha256": HASH_A},
            {"kind": "rights", "sha256": HASH_B},
        ],
    }


def test_runtime_component_instance_owns_parameters_bindings_and_outputs(tmp_path):
    output = tmp_path / "component.html"
    output.write_text("<p>lower third</p>", encoding="utf-8")
    service = ComponentInstanceService(_workspace(tmp_path))
    instance = service.register(
        _instance(output),
        parameter_schema={
            "type": "object",
            "required": ["handle"],
            "properties": {"handle": {"type": "string", "pattern": "^@"}},
        },
    )
    ref = service.implementation_reference(
        instance["instanceId"], adapter_id="hyperframes"
    )
    assert ref["componentInstanceId"] == "instance-lower-third"
    assert ref["sha256"] == instance["instanceHash"]


def test_component_parameter_contract_and_external_scaffold_fail_closed(tmp_path):
    output = tmp_path / "component.html"
    output.write_text("x", encoding="utf-8")
    service = ComponentInstanceService(_workspace(tmp_path))
    with pytest.raises(ComponentInstanceError, match="parameter contract"):
        service.register(
            _instance(output),
            parameter_schema={
                "type": "object",
                "required": ["unknown"],
            },
        )
    scaffold = service.scaffold("custom-criticism-card")
    assert str(tmp_path) in scaffold["path"]
    manifest = (
        tmp_path
        / "edit"
        / "derived"
        / "components"
        / "custom-criticism-card"
        / "component.json"
    )
    assert manifest.is_file()
