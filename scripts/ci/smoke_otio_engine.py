"""Exercise OTIO using only a disposable packaged engine, without media or network."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def _run(engine, arguments, *, env, data=None, expected=0):
    result = subprocess.run(
        [str(engine), *arguments],
        input=data,
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )
    if result.returncode != expected:
        raise RuntimeError(
            f"Native import smoke failed ({result.returncode}): {result.stderr.decode(errors='replace')[:2048]}"
        )
    return json.loads(result.stdout)


def _document(missing):
    def clock(value):
        return {"OTIO_SCHEMA": "RationalTime.1", "value": value, "rate": 24}

    span = {"OTIO_SCHEMA": "TimeRange.1", "start_time": clock(0), "duration": clock(24)}
    clip = {
        "OTIO_SCHEMA": "Clip.1",
        "name": "Synthetic original",
        "source_range": span,
        "media_reference": {
            "OTIO_SCHEMA": "ExternalReference.1",
            "target_url": missing.as_uri(),
            "available_range": span,
        },
    }
    track = {"OTIO_SCHEMA": "Track.1", "kind": "Video", "children": [clip]}
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": "Native import smoke",
        "tracks": {"OTIO_SCHEMA": "Stack.1", "children": [track]},
    }


def smoke(engine, work):
    engine, work = engine.resolve(), work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    raw = work / "raw"
    raw.mkdir(exist_ok=True)
    source = work / "timeline.otio"
    source.write_text(
        json.dumps(_document(raw / "missing-original.mov")), encoding="utf-8"
    )
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "otio-smoke", "videoId": "otio-smoke", "rawDir": str(raw)}
        ),
        encoding="utf-8",
    )
    declarations = work / "declarations.json"
    declarations.write_text(
        json.dumps(
            {
                "sourceOnly": True,
                "output": {
                    "width": 640,
                    "height": 360,
                    "frameRate": {"num": 24, "den": 1},
                    "audioSampleRate": 48000,
                    "channelLayout": "stereo",
                },
            }
        ),
        encoding="utf-8",
    )
    marker = work / "plugin-executed.txt"
    plugin = work / "hostile.py"
    plugin.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nraise RuntimeError('must not load')\n",
        encoding="utf-8",
    )
    manifest = work / "hostile-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "PluginManifest.1",
                "adapters": [
                    {
                        "OTIO_SCHEMA": "PythonPlugin.1",
                        "name": "hostile",
                        "filepath": str(plugin),
                        "suffixes": ["otio"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "AVO_ROOT": "",
        "OTIO_PLUGIN_MANIFEST_PATH": str(manifest),
        "OTIO_DEFAULT_MEDIA_LINKER": "hostile",
    }
    inspected = _run(
        engine,
        ["cli", "timeline-import", "inspect", "--input", str(source), "--json"],
        env=env,
    )
    assert inspected["readiness"]["semanticValidation"] == "not-checked"
    semantic = _run(
        engine, ["otio-worker", "--worker"], env=env, data=source.read_bytes()
    )
    assert semantic["nativeVersion"] == "0.18.1" and semantic["timelines"]
    provider = engine.parent / "_internal" / "providers" / "otio-smoke"
    if provider.exists():
        raise RuntimeError(
            "Use a disposable engine: smoke provider must not already exist"
        )
    assert provider.parent.joinpath("avo.provider.schema.json").is_file()
    provider.mkdir()
    provider_file = provider / "avo.provider.json"
    try:
        provider_file.write_text(
            json.dumps(
                {
                    "name": "otio-smoke",
                    "kind": "generic",
                    "media": {"rawRoot": str(raw)},
                }
            ),
            encoding="utf-8",
        )
        prepared = _run(
            engine,
            [
                "cli",
                "timeline-import",
                "prepare",
                "--project",
                str(project),
                "--input",
                str(source),
                "--declarations",
                str(declarations),
                "--actor",
                "ci-fixture",
                "--reason",
                "Native reader qualification",
                "--json",
            ],
            env=env,
        )
        validated = _run(
            engine,
            [
                "cli",
                "timeline-import",
                "validate",
                "--project",
                str(project),
                "--import-id",
                prepared["importId"],
                "--json",
            ],
            env=env,
            expected=3,
        )
        assert validated["readiness"]["semanticValidation"] == "passed", validated
        assert validated["readiness"]["mediaReady"] == "failed"
        assert validated["readiness"]["activationAllowed"] is False
        assert not (raw / "edit/timeline/cmap.json").exists()
        assert not marker.exists()
        licenses = list(
            engine.parent.rglob("opentimelineio-*.dist-info/licenses/LICENSE.txt")
        )
        assert licenses and all(
            path.with_name("NOTICE.txt").is_file() for path in licenses
        )
        print(
            json.dumps(
                {
                    "status": "pass",
                    "nativeVersion": semantic["nativeVersion"],
                    "semanticValidation": "passed",
                    "mediaReady": "failed-as-expected",
                    "pluginsExecuted": False,
                    "licensesBundled": True,
                }
            )
        )
    finally:
        provider_file.unlink(missing_ok=True)
        provider.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    smoke(args.engine, args.work)


if __name__ == "__main__":
    main()
