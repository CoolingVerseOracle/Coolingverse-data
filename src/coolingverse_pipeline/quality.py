from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class QualityReport:
    region_code: str
    risk_rows: int
    table_rows: dict[str, int]
    apartment_match_rate: float
    enforcement_match_rate: float
    previous_row_deltas: dict[str, float]
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def validate(
    *, region_code: str, grids: pd.DataFrame, apartments: pd.DataFrame,
    enforcement: pd.DataFrame, air_quality: pd.DataFrame, risk: pd.DataFrame,
    previous_table_rows: dict[str, int] | None = None,
) -> QualityReport:
    failures: list[str] = []
    for name, frame in (("grids", grids), ("apartments", apartments), ("enforcement", enforcement),
                        ("air_quality", air_quality), ("risk", risk)):
        if "region_code" not in frame or frame["region_code"].isna().any():
            failures.append(f"{name}: region_code 누락")
        elif set(frame["region_code"].astype(str).unique()) != {region_code}:
            failures.append(f"{name}: 지역 혼입")

    grid_codes = set(grids["grid_code"])
    bad_risk_grids = set(risk["grid_code"].dropna()) - grid_codes
    if bad_risk_grids:
        failures.append("risk: 실제 지역과 grid_code 불일치")
    keys = ["pipeline_run_id", "region_code", "grid_code", "analysis_year", "analysis_month", "hour_of_day"]
    if risk.duplicated(keys).any():
        failures.append("risk: 복합키 중복")
    components = ["demand_pressure", "supply_shortage", "traffic_congest", "env_sensitivity"]
    if not risk[components].apply(lambda s: s.between(0, 1).all()).all():
        failures.append("risk: 구성요소가 0~1 범위를 벗어남")
    if not risk["risk_score"].between(0, 100).all():
        failures.append("risk: 최종 점수가 0~100 범위를 벗어남")
    if not risk["analysis_month"].between(1, 12).all() or not risk["hour_of_day"].between(0, 23).all():
        failures.append("risk: 월 또는 시간이 범위를 벗어남")
    if air_quality[["no2", "co"]].isna().any().any():
        failures.append("air_quality: 보정 후 no2/co 결측")

    apartment_rate = float(apartments["grid_code"].notna().mean()) if len(apartments) else 0.0
    enforcement_rate = float(enforcement["grid_code"].notna().mean()) if len(enforcement) else 0.0
    if apartment_rate < 1.0:
        failures.append(f"apartments: 좌표 매칭률 {apartment_rate:.2%} < 100%")
    if enforcement_rate < 0.99:
        failures.append(f"enforcement: 좌표 매칭률 {enforcement_rate:.2%} < 99%")

    table_rows = {
        "grids": len(grids), "apartments": len(apartments), "enforcement": len(enforcement),
        "air_quality": len(air_quality), "risk_index": len(risk),
    }
    deltas: dict[str, float] = {}
    for table, previous in (previous_table_rows or {}).items():
        if table not in table_rows or not previous:
            continue
        delta = (table_rows[table] - previous) / previous
        deltas[table] = delta
        if abs(delta) > 0.05:
            failures.append(f"{table}: 직전 승인본 대비 행 수 변화 {delta:.2%}")
    if failures:
        raise ValueError("품질 게이트 실패:\n- " + "\n- ".join(failures))
    return QualityReport(region_code, len(risk), table_rows, apartment_rate, enforcement_rate, deltas, True)
