"""위험지수 성분 산출 규칙 — 기존 지역(판교·부천·산본·일산) 모델과 동일해야 한다.

세 성분의 척도가 어긋나면 지역 간 비교가 깨진다. 평촌 최초 산출본은 이 세 곳이 달라
시간대 진폭이 28.3점(일산 5.1점)까지 부풀었다.
"""

from __future__ import annotations

import pandas as pd

from coolingverse_pipeline.risk import calculate_region_risk

REGION = "pyeongchon"
LAT, LNG = 37.394, 126.963


def build(*, enforcement_counts: dict[str, int], no2: float = 0.02, co: float = 0.4) -> pd.DataFrame:
    codes = sorted(enforcement_counts)
    grids = pd.DataFrame({
        "region_code": REGION, "grid_code": codes,
        "center_lat": [LAT + i * 0.01 for i in range(len(codes))],
        "center_lng": [LNG + i * 0.01 for i in range(len(codes))],
    })
    enforcement = pd.DataFrame({
        "region_code": REGION,
        "grid_code": [code for code, n in enforcement_counts.items() for _ in range(n)],
        "enforced_at": "2025-10-01",
    })
    apartments = pd.DataFrame({"region_code": REGION, "grid_code": codes, "open_count": 10})
    air = pd.DataFrame([
        {"region_code": REGION, "grid_code": codes[0], "analysis_month": 10, "hour_of_day": hour,
         "lat": LAT, "lng": LNG, "no2": no2, "co": co}
        for hour in range(24)
    ])
    return calculate_region_risk(region_code=REGION, analysis_year=2025, pipeline_run_id="test",
                                 grids=grids, enforcement=enforcement, apartments=apartments, air_quality=air)


def test_demand_pressure_uses_log_scale() -> None:
    """단속이 극단적으로 몰린 격자 하나가 척도를 독점하면 나머지가 전부 0 근처로 눌린다."""
    risk = build(enforcement_counts={"A": 1, "B": 50, "C": 2000})
    demand = risk.groupby("grid_code").demand_pressure.first()

    # 선형 정규화면 B는 50/2000 = 0.025 로 바닥에 붙는다. 로그 척도에서는 중간값을 갖는다.
    assert demand["B"] > 0.4
    assert demand["A"] < demand["B"] < demand["C"]


def test_traffic_congest_varies_by_grid() -> None:
    """교통 혼잡도는 격자 수요압박에 시간 계수를 곱한 값 — 전 격자가 같은 값이면 안 된다."""
    risk = build(enforcement_counts={"A": 1, "B": 2000})
    at_peak = risk.loc[risk.hour_of_day == 8].set_index("grid_code").traffic_congest

    assert at_peak["A"] != at_peak["B"]


def test_traffic_congest_peaks_follow_commute_hours() -> None:
    """출퇴근 시간대가 새벽보다 높아야 M-커브가 성립한다.

    수요압박이 min-max 정규화라 격자가 하나뿐이면 전부 0이 된다. 최저 격자의 혼잡도가
    항상 0인 것도 기존 모델과 같은 특성이므로, 격자를 둘 이상 두고 확인한다.
    """
    risk = build(enforcement_counts={"A": 1, "B": 100})
    hourly = risk.groupby("hour_of_day").traffic_congest.mean()

    assert hourly[8] > hourly[3]
    assert hourly[18] > hourly[3]


def test_env_sensitivity_is_absolute_not_relative() -> None:
    """기준 농도 대비 절대 비율 — 측정값이 모두 같아도 0이 되지 않는다.

    min-max 정규화였다면 상수 입력이 전부 0이 되고, 반대로 측정소가 적으면
    일주기가 0~1 전 범위를 차지해 시간 변동이 공간 민감도로 둔갑한다.
    """
    risk = build(enforcement_counts={"A": 10}, no2=0.02, co=0.4)
    env = risk.env_sensitivity

    assert (env > 0).all()
    assert env.nunique() == 1  # 농도가 일정하면 시간대별로 흔들리지 않는다
    expected = 0.6 * 0.02 / 0.075 + 0.4 * 0.4 / 1.79
    assert abs(env.iloc[0] - expected) < 1e-9


def test_env_sensitivity_is_capped_at_one() -> None:
    """기준 농도를 크게 넘겨도 성분은 0~1 범위를 유지해야 한다(품질 게이트 조건)."""
    risk = build(enforcement_counts={"A": 10}, no2=5.0, co=90.0)

    assert (risk.env_sensitivity == 1.0).all()
