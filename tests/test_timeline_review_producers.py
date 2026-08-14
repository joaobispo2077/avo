from __future__ import annotations

from pathlib import Path

from avo.adapters.qc.registry import CheckpointQcRegistry


class Store:
    def __init__(self, kind):
        self.kind = kind
    def revision(self, revision_id):
        return {"contentHash": self.kind[0] * 64, "snapshot": {"cues": []}}


class Workspace:
    def __init__(self, root: Path):
        self.raw_dir = root
    def require_active(self, kind):
        return {"headRevisionId": f"{kind}-r0001"}
    def store(self, kind):
        return Store(kind)


def base_check(self, candidate, **request):
    return {
        "status": "pass",
        "duration": 2.0,
        "coverage": {"mode": "full", "windows": request.get("risk_windows") or []},
        "requiredWindows": request.get("risk_windows") or [],
        "evidence": [
            {"kind": "lineage", "status": "pass", "findings": []},
            {"kind": "technical-qc", "status": "pass", "findings": []},
            {"kind": "sync", "status": "pass", "findings": []},
        ],
        "findings": [],
        "tool": "fixture",
        "toolVersion": "1",
    }


def test_motion_producers_cover_layers_audio_visual_rights(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "avo.adapters.qc.registry.CutProofQcAdapter.check", base_check,
    )
    monkeypatch.setattr(
        CheckpointQcRegistry, "_probe",
        staticmethod(lambda candidate: {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio", "channels": 2}],
        }),
    )
    (tmp_path / "SOURCE-LOG.md").write_text("# Sources\n- owned recording\n", encoding="utf-8")
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"x")
    deps = {
        "bmap": "b" * 64,
        "tracks": "t" * 64,
        "animation": "a" * 64,
        "sourceUsage": "s" * 64,
    }
    result = CheckpointQcRegistry().check(
        candidate, checkpoint="motion-proof",
        workspace=Workspace(tmp_path), dependencies=deps,
        risk_windows=[{"start": 0.1, "end": 0.2, "reason": "overlay"}],
    )
    assert {item["kind"] for item in result["evidence"]} == {
        "lineage", "technical-qc", "bmap", "tracks", "animation",
        "visual-qc", "audio-qc", "rights",
    }
    assert result["status"] == "pass"


def test_unresolved_rights_is_human_judgment_finding(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "avo.adapters.qc.registry.CutProofQcAdapter.check", base_check,
    )
    monkeypatch.setattr(
        CheckpointQcRegistry, "_probe",
        staticmethod(lambda candidate: {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}),
    )
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"x")
    result = CheckpointQcRegistry().check(
        candidate, checkpoint="pre-master",
        workspace=Workspace(tmp_path),
        dependencies={"sync-map": "s" * 64},
        risk_windows=[],
    )
    rights = next(item for item in result["evidence"] if item["kind"] == "rights")
    assert rights["status"] == "fail"
    assert rights["findings"][0]["classification"] == "rights"
