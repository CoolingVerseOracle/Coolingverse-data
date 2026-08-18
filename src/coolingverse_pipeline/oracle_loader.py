from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import oracledb
import pandas as pd


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    """이름 바인드용 레코드로 변환한다. 결측은 None으로 바꿔 Oracle NULL로 넣는다.

    번호 바인드(:1)는 thin 드라이버가 '출현 순서'로 세기 때문에 같은 값을 두 번 참조하면
    바인드 개수가 어긋난다(DPY-4009). 이름 바인드는 반복 참조해도 안전하다.
    """
    selected = frame[columns]
    return selected.where(pd.notna(selected), None).to_dict("records")


@contextmanager
def connect(*, user: str, password: str, dsn: str, wallet_dir: str, wallet_password: str) -> Iterator[oracledb.Connection]:
    connection = oracledb.connect(
        user=user, password=password, dsn=dsn, config_dir=wallet_dir,
        wallet_location=wallet_dir, wallet_password=wallet_password,
    )
    try:
        yield connection
    finally:
        connection.close()


def stage_and_activate(
    connection: oracledb.Connection, *, run_id: str, region_code: str, analysis_year: int,
    input_version: str, manifest_sha256: str, quality_report: dict[str, object],
    grids_csv: Path, apartments_csv: Path, enforcement_csv: Path, air_csv: Path, risk_csv: Path,
) -> None:
    """새 실행을 옆에 적재한 뒤 활성 포인터만 한 트랜잭션으로 바꾼다."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO data_pipeline_runs
               (pipeline_run_id, region_code, analysis_year, status, input_version,
                input_manifest_sha256, quality_report)
               VALUES (:1,:2,:3,'STAGING',:4,:5,:6)""",
            [run_id, region_code, analysis_year, input_version, manifest_sha256, json.dumps(quality_report)],
        )
        grids = pd.read_csv(grids_csv, dtype={"grid_code": str})
        cursor.executemany(
            """MERGE INTO grids g USING (SELECT :region_code region_code, :grid_code grid_code FROM dual) s
               ON (g.region_code=s.region_code AND g.grid_code=s.grid_code)
               WHEN NOT MATCHED THEN INSERT
                 (region_code,district_id,grid_code,center_lat,center_lng,min_lat,min_lng,max_lat,max_lng,area_km2,effective_area_km2)
               VALUES (:region_code,(SELECT district_id FROM districts WHERE region_code=:region_code),:grid_code,
                       :center_lat,:center_lng,:min_lat,:min_lng,:max_lat,:max_lng,:area_km2,:effective_area_km2)""",
            _records(grids, ["region_code", "grid_code", "center_lat", "center_lng", "min_lat", "min_lng",
                             "max_lat", "max_lng", "area_km2", "effective_area_km2"]),
        )
        code = {"grid_code": str}
        _replace_source_rows(cursor, "apartments", run_id, region_code, pd.read_csv(apartments_csv, dtype=code))
        _replace_source_rows(cursor, "enforcement", run_id, region_code, pd.read_csv(enforcement_csv, dtype=code))
        _replace_source_rows(cursor, "air_quality", run_id, region_code, pd.read_csv(air_csv, dtype=code))
        risk = pd.read_csv(risk_csv, dtype=code)
        risk_rows = _records(risk, [
            "pipeline_run_id", "region_code", "grid_code", "analysis_year", "analysis_month", "hour_of_day",
            "demand_pressure", "supply_shortage", "traffic_congest", "env_sensitivity", "risk_score",
        ])
        cursor.executemany(
            """INSERT INTO risk_index
               (pipeline_run_id,region_code,grid_id,analysis_year,analysis_month,hour_of_day,
                demand_pressure,supply_shortage,traffic_congest,env_sensitivity,risk_score,batch_date)
               SELECT :pipeline_run_id,:region_code,g.grid_id,:analysis_year,:analysis_month,:hour_of_day,
                      :demand_pressure,:supply_shortage,:traffic_congest,:env_sensitivity,:risk_score,SYSDATE
               FROM grids g WHERE g.region_code=:region_code AND g.grid_code=:grid_code""",
            risk_rows,
        )
        if cursor.rowcount != len(risk_rows):
            raise ValueError(
                f"위험지수 격자 자연키 매핑 실패: expected={len(risk_rows)}, inserted={cursor.rowcount}"
            )
        cursor.execute("UPDATE data_pipeline_runs SET status='VALIDATED' WHERE pipeline_run_id=:1", [run_id])
        cursor.execute(
            "SELECT active_run_id FROM active_dataset_versions WHERE region_code=:1 AND analysis_year=:2",
            [region_code, analysis_year],
        )
        previous = cursor.fetchone()
        cursor.execute(
            """MERGE INTO active_dataset_versions a USING
                 (SELECT :1 region_code, :2 analysis_year, :3 run_id FROM dual) s
               ON (a.region_code=s.region_code AND a.analysis_year=s.analysis_year)
               WHEN MATCHED THEN UPDATE SET previous_run_id=a.active_run_id, active_run_id=s.run_id, activated_at=CURRENT_TIMESTAMP
               WHEN NOT MATCHED THEN INSERT (region_code,analysis_year,active_run_id)
                 VALUES (s.region_code,s.analysis_year,s.run_id)""", [region_code, analysis_year, run_id],
        )
        cursor.execute("UPDATE data_pipeline_runs SET status='ACTIVE', activated_at=CURRENT_TIMESTAMP WHERE pipeline_run_id=:1", [run_id])
        if previous:
            cursor.execute("UPDATE data_pipeline_runs SET status='VALIDATED' WHERE pipeline_run_id=:1", [previous[0]])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def rollback_active(connection: oracledb.Connection, *, region_code: str, analysis_year: int) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT active_run_id, previous_run_id FROM active_dataset_versions WHERE region_code=:1 AND analysis_year=:2",
            [region_code, analysis_year],
        )
        versions = cursor.fetchone()
        if versions is None or versions[1] is None:
            raise ValueError("복구할 이전 활성 실행이 없습니다.")
        cursor.execute(
            """UPDATE active_dataset_versions SET active_run_id=previous_run_id, previous_run_id=active_run_id,
               activated_at=CURRENT_TIMESTAMP WHERE region_code=:1 AND analysis_year=:2 AND previous_run_id IS NOT NULL""",
            [region_code, analysis_year],
        )
        cursor.execute("UPDATE data_pipeline_runs SET status='ROLLED_BACK' WHERE pipeline_run_id=:1", [versions[0]])
        cursor.execute("UPDATE data_pipeline_runs SET status='ACTIVE' WHERE pipeline_run_id=:1", [versions[1]])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def _replace_source_rows(cursor: oracledb.Cursor, table: str, run_id: str, region: str, frame: pd.DataFrame) -> None:
    # 운영 적재 컬럼은 테이블별 whitelist만 허용하며 지역키를 쿼리에 직접 넣는다.
    specs = {
        "apartments": ["grid_code", "kapt_code", "name", "address", "lat", "lng", "total_parking", "is_open", "open_count", "source"],
        "enforcement": ["grid_code", "place_text", "lat", "lng", "enforced_at", "day_of_week", "geocode_status"],
        "air_quality": ["grid_code", "station_name", "lat", "lng", "measured_at", "analysis_month", "day_of_week", "hour_of_day", "no2", "co"],
    }
    columns = specs[table]
    db_columns = ["month" if c == "analysis_month" else "hour" if c == "hour_of_day" else c for c in columns]
    grid_expr = "(SELECT grid_id FROM grids WHERE region_code=:region AND grid_code=:grid_code)"
    non_grid = columns[1:]
    query = (f"INSERT INTO {table} (pipeline_run_id,region_code,grid_id,{','.join(db_columns[1:])}) "
             f"VALUES (:run_id,:region,{grid_expr},{','.join(':'+c for c in non_grid)})")
    rows = [{"run_id": run_id, "region": region, **row} for row in _records(frame, columns)]
    cursor.executemany(query, rows)
