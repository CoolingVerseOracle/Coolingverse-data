from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

#: 시간대 교통 가중치 — 판교·부천·산본·일산을 산출한 기존 모델과 동일한 값.
#: 교통 혼잡도는 이 값 자체가 아니라 격자 수요압박에 곱해지는 계수로 쓰인다(아래 참고).
TRAFFIC_WEIGHTS = np.array([
    0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.8, 1.3,
    1.3, 1.3, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
    1.0, 1.3, 1.3, 1.3, 1.3, 0.8, 0.7, 0.7,
])
#: 교통 가중치 정규화 분모(최댓값) — 계수를 0~1로 되돌린다.
TRAFFIC_WEIGHT_MAX = 1.3

#: 환경 민감도 환산 기준 농도 — 상대 정규화 대신 절대 기준 대비 비율로 환산한다.
#: 측정소 수가 적은 지역에서 min-max를 쓰면 측정소 일주기가 0~1 전 범위를 차지해
#: 시간 변동이 공간 민감도로 둔갑한다(평촌 진폭 28.3점의 주원인).
NO2_REFERENCE_PPM = 0.075
CO_REFERENCE_PPM = 1.79
NO2_ENV_WEIGHT = 0.6
CO_ENV_WEIGHT = 0.4


def _minmax(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    span = numeric.max() - numeric.min()
    return pd.Series(np.zeros(len(numeric)), index=numeric.index) if span == 0 else (numeric - numeric.min()) / span


def _assert_region(frame: pd.DataFrame, region: str, name: str) -> pd.DataFrame:
    if "region_code" not in frame:
        raise ValueError(f"{name}.region_code 누락")
    actual = set(frame["region_code"].dropna().astype(str).unique())
    if actual != {region}:
        raise ValueError(f"{name} 지역 혼입: expected={region}, actual={sorted(actual)}")
    return frame.copy()


def _air_for_grids(grids: pd.DataFrame, air: pd.DataFrame, month: int) -> pd.DataFrame:
    monthly = air.loc[air["analysis_month"] == month].copy()
    monthly[["no2", "co"]] = monthly[["no2", "co"]].apply(pd.to_numeric, errors="coerce")
    # fallback은 같은 지역·월 안에서만 수행한다.
    monthly[["no2", "co"]] = monthly.groupby("hour_of_day")[["no2", "co"]].transform(lambda s: s.fillna(s.mean()))
    if monthly[["no2", "co"]].isna().any().any():
        monthly[["no2", "co"]] = monthly[["no2", "co"]].fillna(monthly[["no2", "co"]].mean())

    rows: list[pd.DataFrame] = []
    for hour in range(24):
        stations = monthly.loc[monthly["hour_of_day"] == hour]
        if stations.empty:
            raise ValueError(f"대기질 자료 없음: month={month}, hour={hour}")
        tree = cKDTree(stations[["lat", "lng"]].to_numpy(float))
        _, index = tree.query(grids[["center_lat", "center_lng"]].to_numpy(float), k=1)
        selected = stations.iloc[np.asarray(index)][["no2", "co"]].reset_index(drop=True)
        selected["grid_code"] = grids["grid_code"].to_numpy()
        selected["hour_of_day"] = hour
        rows.append(selected)
    result = pd.concat(rows, ignore_index=True)
    # 기준 농도 대비 절대 비율 — 지역·측정소 수와 무관하게 같은 척도를 쓴다
    result["env_sensitivity"] = np.minimum(1.0, (
        NO2_ENV_WEIGHT * result["no2"] / NO2_REFERENCE_PPM
        + CO_ENV_WEIGHT * result["co"] / CO_REFERENCE_PPM
    ))
    return result[["grid_code", "hour_of_day", "env_sensitivity"]]


def calculate_region_risk(
    *, region_code: str, analysis_year: int, pipeline_run_id: str,
    grids: pd.DataFrame, enforcement: pd.DataFrame, apartments: pd.DataFrame, air_quality: pd.DataFrame,
) -> pd.DataFrame:
    """한 지역만 받아 지역×연도×월 단위로 정규화하고 24시간 위험지수를 만든다."""
    grids = _assert_region(grids, region_code, "grids")
    enforcement = _assert_region(enforcement, region_code, "enforcement")
    apartments = _assert_region(apartments, region_code, "apartments")
    air_quality = _assert_region(air_quality, region_code, "air_quality")

    valid_codes = set(grids["grid_code"])
    for name, frame in (("enforcement", enforcement), ("apartments", apartments), ("air_quality", air_quality)):
        referenced = set(frame["grid_code"].dropna()) if "grid_code" in frame else set()
        invalid = referenced - valid_codes
        if invalid:
            raise ValueError(f"{name}가 다른 지역 격자를 참조함: {sorted(invalid)[:5]}")

    enforcement["enforced_at"] = pd.to_datetime(enforcement["enforced_at"])
    enforcement = enforcement.loc[enforcement["enforced_at"].dt.year == analysis_year].copy()
    enforcement["analysis_month"] = enforcement["enforced_at"].dt.month
    apartments["open_count"] = pd.to_numeric(apartments["open_count"], errors="coerce").fillna(0)
    supply = apartments.groupby("grid_code", as_index=False)["open_count"].sum()

    outputs: list[pd.DataFrame] = []
    months = sorted(set(air_quality["analysis_month"].astype(int)) & set(enforcement["analysis_month"].astype(int)))
    for month in months:
        demand = (enforcement.loc[enforcement["analysis_month"] == month]
                  .dropna(subset=["grid_code"]).groupby("grid_code").size().rename("count").reset_index())
        base = grids[["region_code", "grid_code", "center_lat", "center_lng"]].merge(demand, how="left").merge(supply, how="left")
        base[["count", "open_count"]] = base[["count", "open_count"]].fillna(0)
        # 로그 변환 후 정규화 — 단속이 극단적으로 몰린 격자 하나가 척도를 독점하는 것을 막는다
        base["demand_pressure"] = _minmax(np.log1p(base["count"]))
        base["supply_shortage"] = 1.0 - _minmax(base["open_count"])
        hourly = base.merge(pd.DataFrame({"hour_of_day": range(24)}), how="cross")
        # 교통 혼잡도 = 격자 수요압박 × 시간 가중계수. 시간 가중치를 그대로 쓰면 전 격자가
        # 같은 값이 되어 "격자 주변 도로 혼잡"이라는 정의가 사라진다.
        hourly["traffic_congest"] = np.minimum(1.0, hourly["demand_pressure"] * (
            TRAFFIC_WEIGHTS[hourly["hour_of_day"].to_numpy(int)] / TRAFFIC_WEIGHT_MAX
        ))
        hourly = hourly.merge(_air_for_grids(base, air_quality, month), on=["grid_code", "hour_of_day"], how="left")
        hourly["analysis_year"] = analysis_year
        hourly["analysis_month"] = month
        hourly["pipeline_run_id"] = pipeline_run_id
        hourly["risk_score"] = 100 * (
            0.35 * hourly["supply_shortage"] + 0.25 * hourly["demand_pressure"]
            + 0.15 * hourly["traffic_congest"] + 0.25 * hourly["env_sensitivity"]
        )
        outputs.append(hourly)
    if not outputs:
        raise ValueError("단속·대기질에 공통으로 존재하는 분석 월이 없습니다.")
    return pd.concat(outputs, ignore_index=True)[[
        "pipeline_run_id", "region_code", "grid_code", "analysis_year", "analysis_month", "hour_of_day",
        "demand_pressure", "supply_shortage", "traffic_congest", "env_sensitivity", "risk_score",
    ]].sort_values(["region_code", "analysis_year", "analysis_month", "grid_code", "hour_of_day"]).reset_index(drop=True)


def stable_risk_hash(frame: pd.DataFrame, region_code: str) -> str:
    regional = frame.loc[frame["region_code"] == region_code].sort_values(
        ["analysis_year", "analysis_month", "grid_code", "hour_of_day"]
    )
    payload = regional.to_csv(index=False, float_format="%.12f", lineterminator="\n").encode()
    return hashlib.sha256(payload).hexdigest()
