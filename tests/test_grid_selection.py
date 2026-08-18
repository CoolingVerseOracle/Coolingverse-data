import pandas as pd

from coolingverse_pipeline.grids import apply_selection, select_active_grids


def sources(*, grids, enforcement, apartments, air_quality):
    return {
        "grids": pd.DataFrame({"grid_code": grids}),
        "enforcement": pd.DataFrame({"grid_code": enforcement}),
        "apartments": pd.DataFrame({"grid_code": apartments}),
        "air_quality": pd.DataFrame({"grid_code": air_quality}),
    }


def test_keeps_apartment_and_air_quality_grids_regardless_of_enforcement():
    """개방 효과가 나올 수 있는 격자와 대기질 측정점은 단속이 없어도 남는다."""
    selection = select_active_grids(
        sources(grids=[1, 2, 3], enforcement=[], apartments=[1], air_quality=[2]), enforcement_min=50
    )

    assert selection.grid_codes == [1, 2]


def test_drops_enforcement_only_grids_below_threshold():
    """단속만 있는 격자는 임계값 미만이면 제외된다 — 희석의 주범이다."""
    selection = select_active_grids(
        sources(grids=[1, 2, 3], enforcement=[2] * 50 + [3] * 49, apartments=[1], air_quality=[1]),
        enforcement_min=50,
    )

    assert selection.grid_codes == [1, 2]


def test_ignores_grids_missing_from_the_grid_table():
    """격자 원천에 없는 코드는 다른 원천이 참조해도 활동 격자가 아니다."""
    selection = select_active_grids(
        sources(grids=[1], enforcement=[9] * 100, apartments=[1, 9], air_quality=[9]), enforcement_min=50
    )

    assert selection.grid_codes == [1]


def test_reports_retention_and_apartment_share():
    """run.json에 남는 근거 수치 — 단속 유지율과 아파트 격자 비중."""
    selection = select_active_grids(
        sources(grids=[1, 2, 3], enforcement=[1] * 60 + [2] * 20 + [3] * 20, apartments=[1], air_quality=[1]),
        enforcement_min=50,
    )

    assert selection.grids_before == 3
    assert selection.enforcement_retained_pct == 60.0
    assert selection.apartment_grid_share_pct == 100.0


def test_apply_selection_filters_every_source():
    """모든 원천이 같은 격자 집합으로 좁혀져야 위험지수 정규화 모수가 일관된다."""
    data = sources(grids=[1, 2], enforcement=[1, 2], apartments=[1, 2], air_quality=[1, 2])
    selection = select_active_grids(data, enforcement_min=50)

    pruned = apply_selection(data, selection)

    assert all(set(frame["grid_code"]) == {1, 2} for frame in pruned.values())
