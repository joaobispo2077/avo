from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from avo.adapters.media.sync_materializer import SyncMaterializer

BUILDER_PATH=Path(__file__).parents[1]/"fixtures"/"timeline"/"build_fixtures.py"
spec=importlib.util.spec_from_file_location("builder",BUILDER_PATH);assert spec and spec.loader
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

def probe(path: Path) -> dict:
 return json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],check=True,capture_output=True,text=True).stdout)

@pytest.mark.skipif(builder.shutil.which("ffmpeg") is None,reason="ffmpeg unavailable")
def test_linear_and_piecewise_materialization_preserve_media_shape(tmp_path: Path) -> None:
 builder.build_fixture_set(tmp_path/"fixtures");raw=tmp_path/"fixtures"/"clean-clock.mp4";materializer=SyncMaterializer()
 linear=tmp_path/"linear.mp4";materializer.materialize(picture_path=raw,audio_path=raw,output_path=linear,transform={"kind":"linear-drift","timebase":{"num":1,"den":1000},"rateRatio":{"num":1001,"den":1000},"offsetTicks":0},sync_revision_hash="a"*64)
 piecewise=tmp_path/"piecewise.mp4";materializer.materialize(picture_path=raw,audio_path=raw,output_path=piecewise,transform={"kind":"piecewise","timebase":{"num":1,"den":1000},"controlPoints":[{"pictureTicks":0,"audioTicks":0},{"pictureTicks":2000,"audioTicks":1998},{"pictureTicks":4000,"audioTicks":4000}]},sync_revision_hash="b"*64)
 for path in (linear,piecewise):
  info=probe(path);assert any(s["codec_type"]=="video" for s in info["streams"]);audio=next(s for s in info["streams"] if s["codec_type"]=="audio");assert int(audio["sample_rate"])==48000 and int(audio["channels"])==1;assert abs(float(info["format"]["duration"])-4.0)<0.15
