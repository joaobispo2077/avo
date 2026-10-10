from avo.adapters.understand.cutting_semantics import CuttingSemanticsAdapter


def test_model_equivalence_remains_inferred_and_binds_actual_identity():
    adapter = CuttingSemanticsAdapter(
        lambda request: {
            "modelIdentity": {"model": "local", "revision": "hash"},
            "response": {
                "equivalent": True,
                "protectedDifferences": [],
                "confidence": 1,
            },
        }
    )
    result = adapter.compare({"groupId": "g", "attempts": []})
    assert result["semanticEquivalence"] is True
    assert result["status"] == "inferred"
    assert result["requiresIndependentEvidence"] is True
    assert len(result["promptHash"]) == len(result["inputHash"]) == 64
    assert "confidence" not in result


def test_missing_identity_and_bad_json_cannot_establish_equivalence():
    adapter = CuttingSemanticsAdapter(lambda request: {"response": "not json"})
    result = adapter.compare({"groupId": "g", "attempts": []})
    assert result["semanticEquivalence"] is None
    assert result["status"] == "blocked"
