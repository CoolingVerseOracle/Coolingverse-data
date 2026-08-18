from __future__ import annotations

import pandas as pd
import pytest

from coolingverse_pipeline.quality import validate
from coolingverse_pipeline.risk import calculate_region_risk, stable_risk_hash

BASE_COORDS = {"pangyo": (37.4, 127.1), "bucheon": (37.5, 126.76), "pyeongchon": (37.394, 126.963)}


def inputs(region: str, demand_multiplier: int = 1) -> tuple[pd.DataFrame, ...]:
    base_lat, base_lng = BASE_COORDS[region]
    grids = pd.DataFrame({
        "region_code": [region, region], "grid_code": ["LOCAL-1", "LOCAL-2"],
        "center_lat": [base_lat, base_lat + 0.01], "center_lng": [base_lng, base_lng + 0.01],
    })
    enforcement = pd.DataFrame({
        "region_code": [region] * (2 * demand_multiplier),
        "grid_code": (["LOCAL-1", "LOCAL-2"] * demand_multiplier),
        "enforced_at": ["2025-10-01"] * (2 * demand_multiplier),
    })
    apartments = pd.DataFrame({
        "region_code": [region, region], "grid_code": ["LOCAL-1", "LOCAL-2"], "open_count": [10, 30],
    })
    air_rows = []
    for hour in range(24):
        air_rows.append({"region_code": region, "grid_code": "LOCAL-1", "analysis_month": 10,
                         "hour_of_day": hour, "lat": base_lat, "lng": base_lng, "no2": 0.02, "co": 0.4})
    return grids, enforcement, apartments, pd.DataFrame(air_rows)


def calculate(region: str, multiplier: int = 1) -> pd.DataFrame:
    grids, enforcement, apartments, air = inputs(region, multiplier)
    return calculate_region_risk(region_code=region, analysis_year=2025, pipeline_run_id=f"run-{region}",
                                 grids=grids, enforcement=enforcement, apartments=apartments, air_quality=air)


def test_bucheon_changes_do_not_change_pangyo_hash() -> None:
    pangyo = calculate("pangyo")
    combined_a = pd.concat([pangyo, calculate("bucheon", 1)], ignore_index=True)
    combined_b = pd.concat([pangyo, calculate("bucheon", 7)], ignore_index=True)
    assert stable_risk_hash(combined_a, "pangyo") == stable_risk_hash(combined_b, "pangyo")


def test_same_local_grid_id_does_not_collide_across_regions() -> None:
    combined = pd.concat([calculate("pangyo"), calculate("bucheon")], ignore_index=True)
    keys = ["pipeline_run_id", "region_code", "grid_code", "analysis_year", "analysis_month", "hour_of_day"]
    assert not combined.duplicated(keys).any()
    assert len(combined) == 96


def test_pyeongchon_addition_does_not_change_pangyo_hash() -> None:
    pangyo = calculate("pangyo")
    combined = pd.concat([pangyo, calculate("pyeongchon")], ignore_index=True)
    assert stable_risk_hash(combined, "pangyo") == stable_risk_hash(pangyo, "pangyo")


def test_annual_collapse_yields_single_month_with_summed_demand() -> None:
    """평촌은 연간 통합 1건이다. 전 행을 한 달에 모으면 수요압력이 연간 합계 순위를 따른다."""
    grids, _, apartments, air = inputs("pyeongchon")
    enforcement = pd.DataFrame({
        "region_code": ["pyeongchon"] * 4,
        "grid_code": ["LOCAL-1", "LOCAL-1", "LOCAL-1", "LOCAL-2"],
        "enforced_at": ["2025-10-02", "2025-10-15", "2025-10-31", "2025-10-08"],
    })
    result = calculate_region_risk(
        region_code="pyeongchon", analysis_year=2025, pipeline_run_id="annual",
        grids=grids, enforcement=enforcement, apartments=apartments, air_quality=air,
    )
    assert set(result["analysis_month"]) == {10}
    assert len(result) == 2 * 24
    at14 = result.query("hour_of_day == 14").set_index("grid_code")
    assert at14.loc["LOCAL-1", "demand_pressure"] == 1.0
    assert at14.loc["LOCAL-2", "demand_pressure"] == 0.0


def test_cross_region_grid_reference_is_rejected() -> None:
    grids, enforcement, apartments, air = inputs("pangyo")
    enforcement.loc[0, "grid_code"] = "BUCHEON-ONLY"
    with pytest.raises(ValueError, match="다른 지역 격자"):
        calculate_region_risk(region_code="pangyo", analysis_year=2025, pipeline_run_id="bad",
                              grids=grids, enforcement=enforcement, apartments=apartments, air_quality=air)


def test_quality_rejects_low_enforcement_match_rate() -> None:
    grids, enforcement, apartments, air = inputs("pangyo")
    enforcement.loc[0, "grid_code"] = None
    risk = calculate("pangyo")
    with pytest.raises(ValueError, match="좌표 매칭률"):
        validate(region_code="pangyo", grids=grids, apartments=apartments, enforcement=enforcement,
                 air_quality=air, risk=risk)


def test_monthly_normalization_never_uses_another_month() -> None:
    grids, enforcement, apartments, air = inputs("pangyo")
    # 10월은 LOCAL-1 수요가 높고, 11월은 LOCAL-2 수요가 높다.
    enforcement = pd.DataFrame({
        "region_code": ["pangyo"] * 6,
        "grid_code": ["LOCAL-1", "LOCAL-1", "LOCAL-1", "LOCAL-2", "LOCAL-2", "LOCAL-1"],
        "enforced_at": ["2025-10-01"] * 3 + ["2025-11-01"] * 3,
    })
    november_air = air.assign(analysis_month=11)
    result = calculate_region_risk(
        region_code="pangyo", analysis_year=2025, pipeline_run_id="monthly",
        grids=grids, enforcement=enforcement, apartments=apartments,
        air_quality=pd.concat([air, november_air], ignore_index=True),
    )
    month10 = result.query("analysis_month == 10 and hour_of_day == 14").set_index("grid_code")
    month11 = result.query("analysis_month == 11 and hour_of_day == 14").set_index("grid_code")
    assert month10.loc["LOCAL-1", "demand_pressure"] == 1.0
    assert month10.loc["LOCAL-2", "demand_pressure"] == 0.0
    assert month11.loc["LOCAL-1", "demand_pressure"] == 0.0
    assert month11.loc["LOCAL-2", "demand_pressure"] == 1.0
