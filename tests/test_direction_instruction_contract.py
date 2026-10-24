"""An explicit reusable instruction is distinct from profile acceptance."""

from copy import deepcopy

import pytest

from avo.timeline.contracts import ContractError, validate_document
from tests.test_direction_contracts import provider_decision_request


def test_explicit_provider_instruction_is_typed_and_optional():
    ordinary = provider_decision_request()
    validate_document(
        ordinary, "avo.direction.schema.json#/$defs/ProviderDecideRequest"
    )
    assert "providerInstruction" not in ordinary
    explicit = deepcopy(ordinary)
    explicit["providerInstruction"] = {
        "text": "Use sound purposefully when it clarifies information.",
        "applicability": {"formats": ["analysis-review"]},
        "exclusions": ["Music-led performance"],
    }
    validate_document(
        explicit, "avo.direction.schema.json#/$defs/ProviderDecideRequest"
    )


def test_instruction_cannot_smuggle_execution_or_omit_its_scope():
    value = provider_decision_request()
    value["providerInstruction"] = {"text": "A preference", "execute": "render"}
    with pytest.raises(ContractError):
        validate_document(
            value, "avo.direction.schema.json#/$defs/ProviderDecideRequest"
        )
