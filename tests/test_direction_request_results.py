from avo.direction.store import DirectionStore
from tests.test_direction_store import document, publish


def test_committed_request_result_stays_exact_after_later_publication(tmp_path):
    store = DirectionStore(tmp_path)
    assert store.request_result("request-one") is None
    original = publish(store, document())
    later = publish(
        store,
        document("record-two"),
        request_id="request-two",
        expected=store.index_hash(),
    )
    assert store.request_result(original["lastRequestId"]) == original
    assert store.load_index() == later
