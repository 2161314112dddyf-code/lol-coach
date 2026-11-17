import math

import pytest

from lol_coach.damage_calculator import calculate_damage


def part(kind, raw):
    return {"label": "test hit", "damage_type": kind, "raw_damage": raw}


def test_mixed_hits_use_separate_resistances_and_keep_fractions_until_total():
    inputs = [part("physical", 90), part("magic", 120), part("true", 25), part("physical", 90)]
    result = calculate_damage(inputs, effective_armor=35, effective_magic_resist=100)
    assert [row["after_resistance"] for row in result["parts"]] == pytest.approx([200/3, 60, 25, 200/3])
    assert result["raw_total"] == 325
    assert result["after_resistance_total"] == pytest.approx(2*200/3 + 85)
    assert inputs == [part("physical", 90), part("magic", 120), part("true", 25), part("physical", 90)]


@pytest.mark.parametrize(("resistance", "result"), [(0, 100), (100, 50), (-50, 400/3), (-100, 150)])
@pytest.mark.parametrize(("kind", "field"), [("magic","effective_magic_resist"), ("physical","effective_armor")])
def test_signed_effective_resistance(resistance, result, kind, field):
    data = calculate_damage([part(kind, 100)], **{field:resistance})
    assert data["after_resistance_total"] == pytest.approx(result)


def test_unknown_is_local_per_hit_and_blocks_only_relevant_total():
    data = calculate_damage([part("physical", 75), part("magic", 100), part("true", 5)], effective_armor=50)
    assert data["raw_total"] == 180 and data["after_resistance_total"] is None
    known, missing, true = data["parts"]
    assert known["after_resistance"] == 50
    assert missing["missing"] == ["effective_magic_resist"]
    assert true["after_resistance"] == 5 and not true["missing"]
    data = calculate_damage([part("magic", None), part("physical", 0)])
    assert data["after_resistance_total"] is data["raw_total"] is None
    assert data["parts"][0]["missing"] == ["raw_damage", "effective_magic_resist"]
    assert data["parts"][1]["after_resistance"] == 0
    assert data["parts"][1]["multiplier"] is None


@pytest.mark.parametrize("value", [True, "100", math.nan, math.inf, -math.inf, 10**1000])
def test_reject_invalid_numeric_inputs(value):
    with pytest.raises(ValueError):
        calculate_damage([part("true", value)])
    with pytest.raises(ValueError):
        calculate_damage([part("physical", 2)], effective_armor=value)


@pytest.mark.parametrize("parts", [[], [part("heal", 100)], [part("physical", -1)],
                                   [part("magic",100) | {"hits":2}], [{}],
                                   [part("true",1e308)]*2, [part("magic",1.7e308)]])
def test_invalid_or_overflowing_hit_scenarios(parts):
    with pytest.raises(ValueError):
        calculate_damage(parts, effective_magic_resist=-100)
