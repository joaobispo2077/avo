import pytest

from avo.timeline.cutting_retakes import group_retakes, select_retake


def take(identity, text, start, complete=True, **extra):
    return {
        "takeId": identity,
        "groupId": "g",
        "text": text,
        "complete": complete,
        "sourceOrder": start,
        "sourceRange": {
            "sourceId": "s",
            "startTicks": start,
            "endTicksExclusive": start + 100,
            "timebase": {"num": 1, "den": 1000},
        },
        **extra,
    }


def evidence(*identities):
    return {
        "semanticEquivalence": True,
        "restartConfirmed": True,
        "perTake": {
            identity: {
                "acousticComplete": True,
                "intelligible": True,
                "intelligibility": 0.9,
                "cadence": 0.8,
                "visualUsability": 0.7,
            }
            for identity in identities
        },
    }


def test_abandoned_start_and_complete_take_are_whole_units():
    group = group_retakes(
        [
            take("a", "uma das", 0, False, abandoned=True),
            take("b", "uma das coisas que interessa", 200),
        ]
    )[0]
    result = select_retake(group, evidence("a", "b"))
    assert result["action"] == "replace"
    assert result["selectedTakeId"] == "b"
    assert result["rejectedTakeIds"] == ["a"]


@pytest.mark.parametrize(
    "left,right",
    [
        ("não é divertido", "é divertido"),
        ("it is not fun", "it is fun"),
        ("alguns jornalistas", "muitos jornalistas"),
        ("only some players", "all players"),
        ("custa 50 reais", "custa 60 reais"),
        ("custa cinquenta reais", "custa sessenta reais"),
    ],
)
def test_qualifier_changes_block_even_model_equivalence(left, right):
    group = group_retakes([take("a", left, 0), take("b", right, 200)])[0]
    assert select_retake(group, evidence("a", "b"))["requiresHuman"] is True


def test_intentional_repetition_is_preserved():
    group = group_retakes(
        [
            take("a", "é importante", 0, intentionalRepetition=True),
            take("b", "é importante", 200),
        ]
    )[0]
    result = select_retake(group, evidence("a", "b"))
    assert result["action"] == "keep"
    assert result["rejectedTakeIds"] == []


def test_overlapping_units_cannot_be_assembled():
    group = group_retakes(
        [take("a", "jogo divertido", 0), take("b", "jogo divertido", 50)]
    )[0]
    assert select_retake(group, evidence("a", "b"))["action"] == "needs-review"


def test_names_are_protected_and_incomplete_last_take_cannot_win():
    group = group_retakes(
        [
            take("a", "Nintendo fez", 0, namedEntities=["Nintendo"]),
            take("b", "Sony fez", 200, namedEntities=["Sony"]),
        ]
    )[0]
    assert select_retake(group, evidence("a", "b"))["requiresHuman"] is True
    group = group_retakes(
        [
            take("a", "a frase completa", 0),
            take("b", "a frase", 200, False, abandoned=True),
        ]
    )[0]
    assert select_retake(group, evidence("a", "b"))["selectedTakeId"] == "a"


def test_abandoned_attempt_qualifier_cannot_be_discarded_as_an_omission():
    group = group_retakes(
        [take("a", "não é", 0, False, abandoned=True), take("b", "é divertido", 200)]
    )[0]
    assert select_retake(group, evidence("a", "b"))["requiresHuman"] is True
