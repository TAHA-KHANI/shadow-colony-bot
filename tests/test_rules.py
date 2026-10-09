from game.randomizer import chance, roll
from services.game_service import alliance_limit, initial_property_count


def test_roll_is_stable_and_bounded():
    assert roll("same-event", 100) == roll("same-event", 100)
    assert 0 <= roll("event", 17) < 17


def test_chance_boundaries():
    assert chance("anything", 100)
    assert not chance("anything", 0)


def test_dynamic_initial_properties():
    assert initial_property_count(5) == 2
    assert initial_property_count(8) == 3
    assert initial_property_count(15) == 4


def test_alliance_size_scales():
    assert alliance_limit(5) == 2
    assert alliance_limit(9) == 3
    assert alliance_limit(15) == 5

