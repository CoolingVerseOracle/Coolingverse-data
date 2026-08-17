from __future__ import annotations

import pandas as pd
import pytest
from prepare_pyeongchon_inputs import ANALYSIS_MONTH, ANALYSIS_YEAR, collapse_to_single_month

# 2025-10의 실제 단속일. 개천절(3), 추석 연휴(6~8), 한글날(9), 주말이 빠진 18일.
OCTOBER_DAYS = [1, 2, 10, 13, 14, 15, 16, 17, 20, 21, 22, 23, 24, 27, 28, 29, 30, 31]


def dates(*values: str) -> pd.Series:
    return pd.to_datetime(pd.Series(values))


def test_all_rows_land_in_the_single_analysis_month() -> None:
    result = collapse_to_single_month(dates("2025-01-02", "2025-06-11", "2025-10-31"), OCTOBER_DAYS)
    assert set(result.dt.year) == {ANALYSIS_YEAR}
    assert set(result.dt.month) == {ANALYSIS_MONTH}


def test_original_weekday_is_preserved() -> None:
    # 수(01-08), 금(06-13), 월(09-08) — 서로 다른 달의 서로 다른 요일.
    source = dates("2025-01-08", "2025-06-13", "2025-09-08")
    result = collapse_to_single_month(source, OCTOBER_DAYS)
    assert result.dt.weekday.tolist() == source.dt.weekday.tolist()


def test_rows_spread_across_all_days_of_their_weekday() -> None:
    """같은 요일 행이 몰리지 않고 해당 요일의 가용 일자에 균등 분배된다."""
    fridays = dates(*(["2025-01-03"] * 8))
    result = collapse_to_single_month(fridays, OCTOBER_DAYS)
    assert sorted(result.dt.day.unique()) == [10, 17, 24, 31]
    assert result.dt.day.value_counts().tolist() == [2, 2, 2, 2]


def test_assigned_days_come_only_from_the_target_pool() -> None:
    # 단속 원본은 평일만 남아 있으므로 영업일 범위로 재현한다.
    source = pd.Series(pd.bdate_range("2025-03-01", "2025-06-30"))
    result = collapse_to_single_month(source, OCTOBER_DAYS)
    assert set(result.dt.day) <= set(OCTOBER_DAYS)
    assert result.dt.weekday.max() <= 4


def test_empty_day_pool_is_rejected() -> None:
    with pytest.raises(ValueError, match="일자 풀"):
        collapse_to_single_month(dates("2025-01-02"), [])


def test_weekday_without_target_day_is_rejected() -> None:
    # 1일(수)만 가용한데 금요일 행이 들어오면 배정할 곳이 없다.
    with pytest.raises(ValueError, match="배정할 요일"):
        collapse_to_single_month(dates("2025-01-03"), [1])
