from __future__ import annotations

from tools import lpc_to_body as lpc


def test_spare_denominator_holes_keep_their_stage_positions(monkeypatch):
    m0 = [(300.0, 0.94), (900.0, 0.95)]
    m100 = [(450.0, 0.96), (1200.0, 0.97), (3200.0, 0.93)]
    answers = iter(["s", "s", "p", "a", "b3", "p", "p"])
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))

    actors = lpc.allocate_actors(m0, m100)

    assert [actor.label if actor else None for actor in actors] == [
        "rank_sketch_1",
        "rank_sketch_2",
        None,
        "anchor_4",
        None,
        None,
    ]


def test_default_active_actor_has_numerator_zero_structure():
    actor = lpc.Actor(
        label="voice",
        pole_m0_hz=900.0,
        radius_m0=0.95,
        pole_m100_hz=1800.0,
        radius_m100=0.96,
        source="test",
    )

    pole_zero = lpc._pole_zero_words(actor, "m0", False)
    all_pole = lpc.allpole_words(actor.pole_m0_hz, actor.radius_m0)

    assert pole_zero != all_pole


def test_default_body_is_four_corners_by_six_rows():
    actors = lpc.allocate_actors([(500.0, 0.95)], [(700.0, 0.96)], sketch_defaults=True)
    lpc.assign_zero_roles(actors, defaults=True)

    assert {label: len(rows) for label, rows in lpc.build_corners(actors).items()} == {
        "M0_Q0": 6,
        "M100_Q0": 6,
        "M0_Q100": 6,
        "M100_Q100": 6,
    }
