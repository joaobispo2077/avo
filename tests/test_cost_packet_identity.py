"""Admitted host evidence cannot borrow another agent/version qualification."""

import pytest

from avo.cost_store import CostError
from test_cost_continuity import packet, registered_ledger
from test_costs import fact


@pytest.mark.parametrize(
    "change", [{"agent": "different-agent"}, {"agentVersion": "unsupported-version"}]
)
def test_host_packet_identity_must_match_its_exact_context_and_profile(
    tmp_path, change
):
    store = registered_ledger(tmp_path)
    before = store.capture()
    with pytest.raises(CostError, match="agent|version|profile"):
        store.ingest_packet(packet(store, [fact(**change)]), allow_synthetic=True)
    assert store.capture() == before
