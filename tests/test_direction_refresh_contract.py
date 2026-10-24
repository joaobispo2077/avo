from avo.direction.rules import seal


def test_packet_can_bind_exact_creator_events_and_acyclic_refresh_report():
    reference = {
        "id": "decision-1",
        "documentHash": "a" * 64,
        "path": "decisions/one.json",
    }
    fields = {
        "provider": "neutral",
        "profileId": "analysis",
        "sourceManifestRef": reference,
        "sourceSetHash": "b" * 64,
        "evidenceRecords": [],
        "coverage": {},
        "limits": {},
        "submissionTemplateVersion": "1.0.0",
        "expectedIndexHash": "absent",
        "providerDecisionRefs": [reference],
        "refreshReportRef": None,
    }
    packet = seal("ProviderInputPacket", fields)
    assert packet["providerDecisionRefs"] == [reference]
    assert packet["refreshReportRef"] is None
