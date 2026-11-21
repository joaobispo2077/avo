"""Proof reuse requires current retained native tool and media evidence."""

from pathlib import Path

import pytest

from avo import artcraft
from avo.timeline import artcraft_audio, artcraft_stills
from avo.timeline.contracts import file_fingerprint
from tests.artcraft_fixtures import locked_tool_observation


@pytest.mark.parametrize(
    ("module", "resolve", "app", "role", "format_name", "evidence"),
    [
        (
            artcraft_audio,
            artcraft_audio.resolve_generated_audio,
            "soundcraft",
            "generated-audio",
            "wav",
            "audioEvidence",
        ),
        (
            artcraft_stills,
            artcraft_stills.read_generated_still,
            "vectorcraft",
            "generated-still",
            "png",
            "stillEvidence",
        ),
    ],
)
def test_generated_media_rejects_a_changed_tool_without_launching_it(
    tmp_path, monkeypatch, module, resolve, app, role, format_name, evidence
):
    job_path = tmp_path / "job.json"
    job_path.write_bytes(b"exact synthetic job")
    export = tmp_path / f"component.{format_name}"
    export.write_bytes(b"retained synthetic media")
    reference = {"job": file_fingerprint(job_path), "exportHead": "b" * 64}
    observation = locked_tool_observation(tmp_path, app)
    retained_job = {
        "observation": observation,
        "output": {"role": role, "format": format_name},
        "inputs": [],
    }
    event = {"outputs": [file_fingerprint(export)], evidence: {}}
    monkeypatch.setattr(
        module, "read_authoring_export", lambda *_args, **_kwargs: (retained_job, event)
    )
    assert resolve(reference) == (retained_job, event)
    application = Path(observation["application"]["locator"])
    application.write_bytes(b"x" * observation["application"]["sizeBytes"])
    with pytest.raises(artcraft.ArtCraftError, match="installation has changed"):
        resolve(reference)
