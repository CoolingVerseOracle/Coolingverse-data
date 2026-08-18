from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import pytest

from coolingverse_pipeline.oracle_loader import stage_and_activate

NAMED_BIND = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


class FakeCursor:
    """실행된 SQL과 바인드를 기록만 하는 커서."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.rowcount = 0

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql: str, rows: list[dict]) -> None:
        self.calls.append((sql, rows))
        self.rowcount = len(rows)

    def fetchone(self):
        return None

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


@pytest.fixture
def loaded(tmp_path) -> FakeCursor:
    grids = pd.DataFrame({
        "region_code": ["pyeongchon"] * 2, "grid_code": ["205596", "205597"],
        "center_lat": [37.36, 37.37], "center_lng": [126.92, 126.93],
        "min_lat": [37.35, 37.36], "min_lng": [126.91, 126.92],
        "max_lat": [37.37, 37.38], "max_lng": [126.93, 126.94],
        "area_km2": [0.01, 0.01], "effective_area_km2": [0.01, 0.01],
    })
    risk = pd.DataFrame({
        "pipeline_run_id": ["run"] * 2, "region_code": ["pyeongchon"] * 2,
        "grid_code": ["205596", "205597"], "analysis_year": [2025] * 2,
        "analysis_month": [10] * 2, "hour_of_day": [0, 1],
        "demand_pressure": [0.1, 0.2], "supply_shortage": [0.3, 0.4],
        "traffic_congest": [0.5, 0.6], "env_sensitivity": [0.7, 0.8],
        "risk_score": [40.0, 50.0],
    })
    frames = {
        "grids": grids, "risk": risk,
        "apartments": pd.DataFrame({
            "region_code": ["pyeongchon"], "grid_code": ["205596"], "kapt_code": ["A1"],
            "name": ["단지"], "address": ["주소"], "lat": [37.36], "lng": [126.92],
            "total_parking": [100], "is_open": ["N"], "open_count": [32], "source": ["K-apt"],
        }),
        "enforcement": pd.DataFrame({
            "region_code": ["pyeongchon"], "grid_code": ["205596"], "place_text": ["장소"],
            "lat": [37.36], "lng": [126.92], "enforced_at": ["2025-10-01"],
            "day_of_week": ["수"], "geocode_status": ["성공"],
        }),
        "air_quality": pd.DataFrame({
            "region_code": ["pyeongchon"], "grid_code": ["205596"], "station_name": ["부림동"],
            "lat": [37.39], "lng": [126.95], "measured_at": ["2025-10-01 00:00"],
            "analysis_month": [10], "day_of_week": ["수"], "hour_of_day": [0],
            "no2": [0.02], "co": [0.4],
        }),
    }
    paths = {}
    for name, frame in frames.items():
        paths[name] = tmp_path / f"{name}.csv"
        frame.to_csv(paths[name], index=False)

    connection = FakeConnection()
    stage_and_activate(
        connection, run_id="run", region_code="pyeongchon", analysis_year=2025,
        input_version="v1", manifest_sha256="abc", quality_report={"passed": True},
        grids_csv=paths["grids"], apartments_csv=paths["apartments"],
        enforcement_csv=paths["enforcement"], air_csv=paths["air_quality"],
        risk_csv=paths["risk"],
    )
    assert connection.committed
    return connection.cursor_obj


def test_every_named_bind_is_supplied(loaded: FakeCursor) -> None:
    """SQL의 모든 이름 바인드가 실제 전달된 키에 존재해야 한다.

    번호 바인드(:1)를 반복 참조하면 thin 드라이버가 출현 횟수만큼 값을 요구해
    DPY-4009로 죽는다. 이름 바인드로 유지되는지 함께 지킨다.
    """
    for sql, params in loaded.calls:
        rows = params if isinstance(params, list) else [params]
        for row in rows:
            if not isinstance(row, dict):
                continue
            missing = set(NAMED_BIND.findall(sql)) - set(row)
            assert not missing, f"바인드 누락 {sorted(missing)}\n{sql}"


def test_date_columns_bind_as_datetime(loaded: FakeCursor) -> None:
    """날짜는 문자열이 아니라 datetime으로 바인딩해야 한다.

    문자열로 넘기면 Oracle이 세션 NLS_DATE_FORMAT(기본 DD-MON-RR)으로 해석하려다
    ORA-01861로 죽는다.
    """
    checked = 0
    for sql, params in loaded.calls:
        for column in ("enforced_at", "measured_at"):
            if not isinstance(params, list) or f":{column}" not in sql:
                continue
            for row in params:
                assert isinstance(row[column], datetime), f"{column}이 {type(row[column]).__name__}로 바인딩됐다"
                checked += 1
    assert checked, "날짜 컬럼을 가진 문장을 하나도 검사하지 못했다"


def test_positional_binds_are_never_repeated(loaded: FakeCursor) -> None:
    """번호 바인드는 한 번만 쓰면 안전하지만 반복 참조하면 깨진다.

    thin 드라이버는 :1 을 세 번 쓰면 값 3개를 요구한다. 같은 값을 두 곳에서 써야 하면
    이름 바인드로 바꿔야 한다.
    """
    for sql, _ in loaded.calls:
        occurrences = re.findall(r":(\d+)", sql)
        repeated = sorted({n for n in occurrences if occurrences.count(n) > 1})
        assert not repeated, f"번호 바인드 {repeated} 반복 참조\n{sql}"
