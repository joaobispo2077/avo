from __future__ import annotations

from datetime import datetime, timezone

import pytest

from avo.timeline.animation import AnimationError
from avo.timeline.provider_animation import ProviderAnimationService
from tests.test_provider_animation_promotion import _rights


def test_rights_fail_closed_for_missing_expired_revoked_or_nonportable():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    valid = _rights()
    report = ProviderAnimationService.validate_rights(valid, now=now)
    assert report["eligible"] is True
    assert report["attributions"] == ["none"]
    assert report["aiDisclosures"] == ["none"]

    cases = [
        [],
        [{**valid[0], "termEndsAt": "2025-01-01T00:00:00Z"}],
        [{**valid[0], "revoked": True}],
        [{**valid[0], "providerWide": False}],
        [{key: value for key, value in valid[0].items() if key != "evidenceRef"}],
    ]
    for entries in cases:
        with pytest.raises(AnimationError, match="rights"):
            ProviderAnimationService.validate_rights(entries, now=now)
