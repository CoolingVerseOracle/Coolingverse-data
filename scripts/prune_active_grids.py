"""활동 격자 재선정 — 단속 희소 격자를 제외하고 위험지수를 다시 만든다.

## 왜 필요한가

위험지수 격자에 아파트가 없으면 개방 효과가 구조적으로 0이다. 그런 격자가 모수에
많이 섞이면 정책 효과가 전 격자 평균에서 희석돼, 지도·M-커브에서 "효과 없음"으로 보인다.

평촌 v2는 877개 격자 중 750개(85.5%)가 단속만 있는 격자였다. 단속 56,552건이 참조하는
격자를 전부 인정한 결과인데, 그중 절반은 연 14건(월 1건) 이하의 희소 격자다.

    지역        격자    아파트 격자    효과 격자    격자당 Δsupply    최대 감소폭
    평촌 v2      877    122 (13.9%)   109 (12.4%)      0.135          -0.59
    일산         646    250 (38.7%)   233 (36.1%)      0.142          -1.80

격자당 효과는 두 지역이 사실상 같다. 3배 차이는 전부 분모에서 나온다.

## 규칙

    활동 격자 = 아파트 보유 격자 ∪ 대기질 측정 격자 ∪ 단속 ENFORCEMENT_MIN건 이상 격자

연 50건(주 1회)을 임계값으로 두면 평촌이 877 → 329개가 되어 아파트 격자 비중이 38.0%로,
일산 38.7%와 같은 수준이 된다. 잘려나간 550개 격자가 갖고 있던 단속은 전체의 11.2%뿐이라
단속 정보는 88.8% 유지되고, baseline도 51.10 → 51.05로 사실상 불변이다.
지역 위험도 수준은 그대로 두고 희석만 걷어내는 것이 이 처리의 목적이다.

임계값을 바꾸면 지역 간 정책효과 비교가 깨진다. 다른 지역을 추가·재적재할 때도
아파트 격자 비중이 일산 수준(약 38%)에 맞는지 확인하고 임계값을 정할 것.

## 실행

    python scripts/prune_active_grids.py <build_output_dir> <output_dir> <pipeline_run_id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coolingverse_pipeline.risk import calculate_region_risk  # noqa: E402

#: 활동 격자로 인정할 연간 최소 단속 건수 (주 1회). 위 문서의 근거 참고.
ENFORCEMENT_MIN = 50

TABLES = ("grids", "enforcement", "apartments", "air_quality")


def select_active_grids(
    *, risk: pd.DataFrame, enforcement: pd.DataFrame, apartments: pd.DataFrame,
    air_quality: pd.DataFrame, enforcement_min: int = ENFORCEMENT_MIN,
) -> list:
    """아파트·대기질 격자는 무조건 남기고, 단속만 있는 격자는 건수 기준으로 거른다."""
    active = set(risk["grid_code"])
    keep = (set(apartments["grid_code"]) | set(air_quality["grid_code"])) & active
    counts = enforcement.loc[enforcement["grid_code"].isin(active)].groupby("grid_code").size()
    sparse_only = counts[~counts.index.isin(keep)]
    return sorted(keep | set(sparse_only[sparse_only >= enforcement_min].index))


def main(source: str, output: str, run_id: str, enforcement_min: int = ENFORCEMENT_MIN) -> None:
    src, out = Path(source), Path(output)
    out.mkdir(parents=True, exist_ok=True)
    frames = {name: pd.read_csv(src / f"{name}.csv") for name in TABLES}
    risk_before = pd.read_csv(src / "risk_index.csv")
    region = str(risk_before["region_code"].iloc[0])
    year = int(risk_before["analysis_year"].iloc[0])

    keep = select_active_grids(risk=risk_before, enforcement=frames["enforcement"],
                               apartments=frames["apartments"], air_quality=frames["air_quality"],
                               enforcement_min=enforcement_min)
    pruned = {name: frame.loc[frame["grid_code"].isin(keep)] for name, frame in frames.items()}

    risk = calculate_region_risk(region_code=region, analysis_year=year, pipeline_run_id=run_id, **pruned)
    for name, frame in {**pruned, "risk_index": risk}.items():
        frame.to_csv(out / f"{name}.csv", index=False)

    apartment_grids = set(pruned["apartments"]["grid_code"])
    retained = len(pruned["enforcement"]) / max(len(frames["enforcement"]), 1) * 100
    run = json.loads((src / "run.json").read_text(encoding="utf-8"))
    run.update({
        "pipeline_run_id": run_id,
        "quality": {**run.get("quality", {}), "risk_rows": len(risk),
                    "table_rows": {**{n: len(f) for n, f in pruned.items()}, "risk_index": len(risk)}},
        "grid_selection": {
            "rule": f"아파트 ∪ 대기질 ∪ 단속 {enforcement_min}건 이상 격자",
            "enforcement_min_per_year": enforcement_min,
            "grids_before": int(risk_before["grid_code"].nunique()), "grids_after": len(keep),
            "enforcement_retained_pct": round(retained, 1),
            "apartment_grid_share_pct": round(len(apartment_grids) / len(keep) * 100, 1),
        },
    })
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"활동 격자 {risk_before['grid_code'].nunique()} → {len(keep)}개 "
          f"(아파트 격자 비중 {len(apartment_grids) / len(keep) * 100:.1f}%)")
    print(f"단속 {len(frames['enforcement']):,}건 → {len(pruned['enforcement']):,}건 ({retained:.1f}% 유지)")
    print(f"위험지수 {len(risk_before):,}행 → {len(risk):,}행 | "
          f"baseline {risk_before.risk_score.mean():.2f} → {risk.risk_score.mean():.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.strip().splitlines()[-1].strip())
    main(*sys.argv[1:])
