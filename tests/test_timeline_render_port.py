from __future__ import annotations

from pathlib import Path

from avo.timeline.materialize import materialize_cut_proof

class FakeRender:
 def __init__(self):self.calls=[]
 def render(self,projection,output,**request):
  self.calls.append((projection,output,request));Path(output).write_bytes(b"proof")
  return {"status":"pass","output":{"sha256":"c"*64,"sizeBytes":5,"locator":str(output)},"path":str(output),"renderProfile":request["profile"],"producer":{"name":"fake","version":"1"}}

def test_materialization_binds_projection_and_exact_dependencies(tmp_path, monkeypatch):
 from tests.test_timeline_cmap_service import workspace,snapshot
 from avo.timeline.cmap_service import CMapService
 ws=workspace(tmp_path);raw=ws.raw_dir/"raw.bin";raw.write_bytes(b"raw");revision=CMapService(ws).author(snapshot(raw),actor="agent",reason="cut")
 fake=FakeRender();record=materialize_cut_proof(workspace=ws,cmap_revision_id=revision["revisionId"],output_path=ws.raw_dir/"edit"/"proof.mp4",render_port=fake)
 assert record["canonicalInputLock"]["cmapRevisionHash"]==revision["contentHash"]
 assert record["output"]["sha256"]=="c"*64
 assert (ws.timeline_dir/"projection.json").is_file()
 assert fake.calls[0][2]["profile"]=="draft"
