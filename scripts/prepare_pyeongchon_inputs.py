"""안양 평촌 인계 산출물을 파이프라인 계약 CSV로 변환한다.

팀 인계본(격자 4,146개 / 단속 56,552행)은 지오코딩과 격자 매핑이 이미 끝나 있으나
컬럼 구성이 계약과 다르다. 이 스크립트는 분석을 다시 하지 않고 표현만 계약에 맞춘다.

평촌은 월별이 아닌 **연간 통합 1건**이다. `analysis_month`는 스키마가 NOT NULL을 요구해
채우는 자리표시자이며 "10월"을 뜻하지 않는다. 전 행을 한 달 슬롯에 모아야
`risk.calculate_region_risk`의 월 루프가 단일 월로 돌면서 격자별 수요가 연간 합계가 된다.
흩어두면 프론트가 조회하는 10월분만 반영되고 나머지가 사장된다.

사용법:
    python scripts/prepare_pyeongchon_inputs.py \
        --source-dir "../data/Anyang Pyeongchon" \
        --output-dir "../data/Anyang Pyeongchon/contract"
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REGION_CODE = "pyeongchon"
ANALYSIS_YEAR = 2025
ANALYSIS_MONTH = 10
WEEKDAY_NAMES = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# 유휴율 — apartments.open_count = total_parking * IDLE_RATE.
# 평일 낮 통근으로 빠져나가 비는 주차면 비율이며, 분당 29.10% / 부천 30.10% / 군포 31.36%에 대응한다.
#
# 분모는 반드시 '통근' 인구여야 한다. 통학 인구(안양 54,368명)를 포함하면 분담률이 34.28%로
# 과소 산출되고, 인접한 군포(39.80%)와 5.5%p나 벌어져 타 지역과 방식이 어긋난다.
# 통근만 쓰면 40.72% vs 39.80%로 0.92%p 차이에 그친다.
APARTMENT_COMMUTE_RATE = 0.788  # 아파트 통근율. 부천·군포에 공통 적용된 기존 상수를 그대로 쓴다.
CAR_COMMUTE_SHARE = 105_529 / 259_171  # KOSIS 인구주택총조사(2020) 안양시 통근 기준 승용차·승합차
IDLE_RATE = APARTMENT_COMMUTE_RATE * CAR_COMMUTE_SHARE  # 0.3209

GRID_COLUMNS = [
    "region_code", "grid_code", "center_lat", "center_lng",
    "min_lat", "min_lng", "max_lat", "max_lng", "area_km2", "effective_area_km2",
]
ENFORCEMENT_COLUMNS = [
    "region_code", "grid_code", "place_text", "lat", "lng",
    "enforced_at", "day_of_week", "geocode_status", "source_enforced_at",
]


def build_grids(source: Path) -> pd.DataFrame:
    """격자에 region_code를 부여하고 계약 10컬럼만 남긴다.

    인계본의 district_id는 전 행이 1(판교 값)이지만 계약 컬럼이 아니므로 버린다.
    적재 시 oracle_loader가 districts 테이블에서 직접 조회한다.
    """
    grids = pd.read_csv(source, encoding="utf-8-sig", dtype={"grid_code": str})
    grids["region_code"] = REGION_CODE
    if grids["grid_code"].duplicated().any():
        raise ValueError("grids: grid_code 중복")
    return grids[GRID_COLUMNS]


def collapse_to_single_month(dates: pd.Series, target_days: list[int]) -> pd.Series:
    """전 행을 분석 월 하나로 모으되 원본 요일을 보존한다.

    수요압력은 (격자, 월) 단위 행 개수라 월 내 일자는 지수에 영향이 없다. 다만 day_of_week은
    DB에 그대로 남으므로, 단순 근접 스냅으로 특정 요일에 몰리지 않도록 각 행을 원본과 같은
    요일의 날짜에만 배정한다(요일 그룹 안에서 균등 분배).

    대상 일자 풀은 원본 데이터의 해당 월 실제 단속일에서 얻으므로 주말과 공휴일이 자동으로
    배제된다(2025-10은 개천절·추석 연휴·한글날이 빠진 18일).
    """
    if not target_days:
        raise ValueError("대상 월에 단속일이 없어 일자 풀을 만들 수 없다")
    pool = pd.to_datetime({"year": ANALYSIS_YEAR, "month": ANALYSIS_MONTH, "day": sorted(target_days)})
    days_by_weekday: dict[int, list[int]] = {}
    for day in pool:
        days_by_weekday.setdefault(day.weekday(), []).append(day.day)

    weekday = dates.dt.weekday
    missing = set(weekday.unique()) - days_by_weekday.keys()
    if missing:
        raise ValueError(f"대상 월에 배정할 요일이 없다: {sorted(missing)}")
    position = dates.groupby(weekday).cumcount()
    assigned = [days_by_weekday[w][p % len(days_by_weekday[w])] for w, p in zip(weekday, position, strict=True)]
    return pd.to_datetime({"year": ANALYSIS_YEAR, "month": ANALYSIS_MONTH, "day": assigned})


def build_enforcement(source: Path, grids: pd.DataFrame, grid_lookup: pd.DataFrame) -> pd.DataFrame:
    """단속 인계본을 계약 형태로 바꾼다.

    인계본의 grid_id는 격자 파일의 grid_id를 가리킨다(grid_code와는 한 건도 겹치지 않는다).
    따라서 grid_id -> grid_code 경로로 자연키를 얻어야 한다.
    """
    enforcement = pd.read_csv(source, encoding="utf-8-sig")
    merged = enforcement.merge(grid_lookup, on="grid_id", how="left", validate="many_to_one")
    unmapped = int(merged["grid_code"].isna().sum())
    if unmapped:
        raise ValueError(f"단속 {unmapped}행의 grid_id가 격자 파일에 없다")

    merged["region_code"] = REGION_CODE
    merged["source_enforced_at"] = merged["enforced_at"]
    original = pd.to_datetime(merged["enforced_at"])
    target_days = sorted(original.loc[original.dt.month == ANALYSIS_MONTH].dt.day.unique().tolist())
    collapsed = collapse_to_single_month(original, target_days)
    merged["enforced_at"] = collapsed.dt.strftime("%Y-%m-%d")
    merged["day_of_week"] = collapsed.dt.weekday.map(lambda index: WEEKDAY_NAMES[index])

    if not merged["grid_code"].isin(set(grids["grid_code"])).all():
        raise ValueError("단속이 격자 파일에 없는 grid_code를 참조한다")
    if collapsed.dt.weekday.max() > 4:
        raise ValueError("주말에 배정된 단속 행이 있다")
    return merged[ENFORCEMENT_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description="안양 평촌 계약 CSV 생성")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--grids-file", default="grids_anyang_final.csv")
    parser.add_argument("--enforcement-file", default="안양시_평촌_단속위치_grid_mapped.csv")
    args = parser.parse_args()

    grids = build_grids(args.source_dir / args.grids_file)
    raw_grids = pd.read_csv(args.source_dir / args.grids_file, encoding="utf-8-sig", dtype={"grid_code": str})
    grid_lookup = raw_grids[["grid_id", "grid_code"]]
    enforcement = build_enforcement(args.source_dir / args.enforcement_file, grids, grid_lookup)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    grids.to_csv(args.output_dir / "grids.csv", index=False, encoding="utf-8")
    enforcement.to_csv(args.output_dir / "enforcement.csv", index=False, encoding="utf-8")

    covered = enforcement["grid_code"].nunique()
    print(f"grids.csv       {len(grids):>7,}행  (단속 발생 격자 {covered:,}개)")
    print(f"enforcement.csv {len(enforcement):>7,}행  "
          f"배정일 {enforcement['enforced_at'].nunique()}일 "
          f"({enforcement['enforced_at'].min()} ~ {enforcement['enforced_at'].max()})")
    print(f"원본 기간       {enforcement['source_enforced_at'].min()} ~ {enforcement['source_enforced_at'].max()}")


if __name__ == "__main__":
    main()
