from tests.test_briefstart import context, reference
from tests.test_briefstart_context import project_fixture

from avo.direction.brief import BriefService
from avo.direction.store import DirectionStore


def test_combined_builtin_and_personal_reference_preserve_labels_and_current_instruction(
    tmp_path,
):
    project = project_fixture(tmp_path)
    service = BriefService(project)
    current = context()
    current["currentInstructions"] = ["Use quiet examples in this particular video."]
    result = service.prepare("builtin:analysis-review@1.0.0", current, [reference()])
    packet = DirectionStore(service.root).load_document(
        result["refs"]["packet"]["path"]
    )
    assert [source["kind"] for source in packet["sources"]] == ["builtin", "reference"]
    assert (
        packet["sources"][1]["document"]["knownUsageLimits"]
        == "No rights or approval transfer."
    )
    assert packet["context"]["currentInstructions"] == current["currentInstructions"]
    assert not (service.root / "index.json").exists()
    assert not (project.parent / "edit/timeline").exists()
