import pytest

from avo import shorts_media, shorts_rules


def test_media_exports_retain_shared_rules_and_exception_identity():
    for name in (
        "MediaPreparationError",
        "finite_repeat_map",
        "validate_windows",
        "validate_source_map",
        "SFX_VOLUME",
        "SFX_ASSET_KEY",
        "SFX_FILE_NAME",
    ):
        assert getattr(shorts_media, name) is getattr(shorts_rules, name)
    windows = [{"startSec": 5, "endSec": 8}]
    result = shorts_rules.finite_repeat_map(windows, 5)
    assert result == [
        {
            "outputStartSec": 0,
            "outputEndSec": 3,
            "sourceStartSec": 5,
            "sourceEndSec": 8,
        },
        {
            "outputStartSec": 3,
            "outputEndSec": 5,
            "sourceStartSec": 5,
            "sourceEndSec": 7,
        },
    ]
    shorts_rules.validate_source_map(result, windows, [], 5)
    with pytest.raises(
        shorts_media.MediaPreparationError, match="overlaps an excluded"
    ):
        shorts_rules.validate_windows(windows, [{"startSec": 6, "endSec": 7}])
