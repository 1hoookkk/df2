from __future__ import annotations

from tools.fit_two_audio_arma import LaneSummary, RootPair, infer_mapping, parse_mapping


def lane(index: int, pole: float, zero: float | None) -> LaneSummary:
    return LaneSummary(
        lane=index,
        pole=RootPair(pole, 0.95, "complex_pair"),
        zero=RootPair(zero, 0.90, "complex_pair") if zero is not None else None,
        gain=0.5,
    )


def test_infer_mapping_uses_pole_zero_geometry_not_input_rank():
    a = [lane(i + 1, pole, zero) for i, (pole, zero) in enumerate([
        (300, 200), (700, 500), (1400, 1000), (2800, 2100), (5600, 4200), (9000, 7000),
    ])]
    b = [a[index] for index in [1, 0, 2, 4, 3, 5]]

    mapping, _cost = infer_mapping(a, b)

    assert mapping == [1, 0, 2, 4, 3, 5]


def test_parse_mapping_accepts_explicit_permutation():
    mapping, source = parse_mapping("1,3,2,4,6,5", list(range(6)))

    assert mapping == [0, 2, 1, 3, 5, 4]
    assert source == "explicit-user"
