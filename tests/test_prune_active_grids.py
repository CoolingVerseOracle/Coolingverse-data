import pandas as pd

from scripts.prune_active_grids import select_active_grids


def frame(pairs, column="grid_code"):
    return pd.DataFrame({column: pairs})


def test_keeps_apartment_and_air_quality_grids_regardless_of_enforcement():
    """개방 효과가 나올 수 있는 격자와 대기질 측정점은 단속이 없어도 남는다."""
    keep = select_active_grids(
        risk=frame([1, 2, 3]),
        enforcement=frame([]),
        apartments=frame([1]),
        air_quality=frame([2]),
        enforcement_min=50,
    )

    assert keep == [1, 2]


def test_drops_enforcement_only_grids_below_threshold():
    """단속만 있는 격자는 임계값 미만이면 제외된다 — 희석의 주범이다."""
    keep = select_active_grids(
        risk=frame([1, 2, 3]),
        enforcement=frame([2] * 50 + [3] * 49),
        apartments=frame([1]),
        air_quality=frame([1]),
        enforcement_min=50,
    )

    assert keep == [1, 2]


def test_ignores_grids_outside_the_risk_index():
    """위험지수가 없는 격자는 원천이 참조해도 활동 격자가 아니다."""
    keep = select_active_grids(
        risk=frame([1]),
        enforcement=frame([9] * 100),
        apartments=frame([1, 9]),
        air_quality=frame([9]),
        enforcement_min=50,
    )

    assert keep == [1]
