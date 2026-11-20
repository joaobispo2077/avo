"""Declared evidence survives a separate process without granting cut authority."""

import json
import os
import subprocess
import sys

import pytest
from tests.test_speech_recovery import recovery
from tests.test_speech_recovery_choices import decision

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("choice", ["recovered", "defer"])
def test_selected_or_deferred_evidence_survives_a_fresh_process(tmp_path, choice):
    cutting, cmap, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    choose = decision(service, shown, choice)
    selected = service.decide(choose)
    path = tmp_path / "resume.json"
    path.write_text(
        json.dumps(
            {
                "project": str(cutting.workspace.project_path),
                "videoId": cutting.workspace.video_id,
                "request": request,
                "decision": choose,
            }
        ),
        encoding="utf-8",
    )
    script = """
import json, pathlib, sys
from avo.timeline.preparation_recovery import PreparationService
from avo.timeline.workspace import TimelineWorkspace
from tests.test_speech_recovery import RecoveryPort
from tests.test_speech_recovery_choices import evidence
data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
workspace = TimelineWorkspace.from_project(pathlib.Path(data['project']), video_id=data['videoId'])
port = RecoveryPort()
def forbidden(*args, **kwargs):
    raise AssertionError('fresh-process selection started inference')
port.recover = forbidden
service = PreparationService(workspace, recovery_port=port)
print(json.dumps({'decision': service.decide(data['decision']), 'evidence': evidence(service, data['request'])}))
"""
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(path)],
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
    resumed = json.loads(completed.stdout)
    assert resumed["decision"]["decisionRef"] == selected["decisionRef"]
    assert resumed["decision"]["cutApproval"] == "not-granted"
    assert resumed["evidence"]["status"] == (
        "selected" if choice == "recovered" else "deferred"
    )
    assert request["ranges"][0] in resumed["evidence"]["protectedRanges"]
    assert cutting.workspace.store("cmap").head_hash() == cmap["contentHash"]
