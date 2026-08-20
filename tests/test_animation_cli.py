from __future__ import annotations

import json
from pathlib import Path

from avo.cli import main
from tests.test_animation_promotion import pattern


def test_provider_animation_cli_propose_decide_recommend(tmp_path: Path, capsys):
    catalog = tmp_path / "animation.json"
    pattern_path = tmp_path / "pattern.json"
    diagnosis_path = tmp_path / "diagnosis.json"
    pattern_path.write_text(json.dumps(pattern()), encoding="utf-8")
    diagnosis_path.write_text(
        json.dumps({"format": "talking-head-review", "constraints": []}),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "animation",
                "propose",
                "--catalog",
                str(catalog),
                "--provider",
                "bishop",
                "--pattern",
                str(pattern_path),
                "--actor",
                "creator",
                "--intent-reference",
                "creator requested reusable C01+C02",
            ]
        )
        == 0
    )
    proposal = json.loads(capsys.readouterr().out)
    assert not catalog.exists()
    assert (
        main(
            [
                "animation",
                "decide",
                "--catalog",
                str(catalog),
                "--provider",
                "bishop",
                "--proposal",
                proposal["path"],
                "--decision",
                "approved",
                "--actor",
                "creator",
                "--reason",
                "sanitized abstraction approved",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "animation",
                "recommend",
                "--catalog",
                str(catalog),
                "--provider",
                "bishop",
                "--diagnosis",
                str(diagnosis_path),
                "--evidence-sha256",
                "b" * 64,
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] is False
    assert [item["patternId"] for item in result["recommendations"]] == ["c01-c02"]
