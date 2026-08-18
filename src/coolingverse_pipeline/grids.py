"""활동 격자 선정 — 위험지수를 부여할 격자를 고른다.

위험지수 격자에 아파트가 없으면 개방 효과가 구조적으로 0이다. 그런 격자가 모수에 많이
섞이면 정책 효과가 전 격자 평균에서 희석돼, 지도·M-커브에서 "효과 없음"으로 보인다.

평촌 v2는 877개 격자 중 750개(85.5%)가 단속만 있는 격자였다. 단속 56,552건이 참조하는
격자를 전부 인정한 결과인데, 그중 절반은 연 14건(월 1건) 이하의 희소 격자다.

    지역        격자    아파트 격자    효과 격자    격자당 Δsupply    최대 감소폭
    평촌 v2      877    122 (13.9%)   109 (12.4%)      0.135          -0.59
    일산         646    250 (38.7%)   233 (36.1%)      0.142          -1.80

격자당 효과는 두 지역이 사실상 같다. 3배 차이는 전부 분모에서 나온다.

연 50건(주 1회)을 임계값으로 두면 평촌이 877 → 329개가 되어 아파트 격자 비중이 38.0%로,
일산 38.7%와 같은 수준이 된다. 잘려나간 550개 격자가 갖고 있던 단속은 전체의 11.2%뿐이라
단속 정보는 88.8% 유지되고, baseline도 51.10 → 51.05로 사실상 불변이다.
지역 위험도 수준은 그대로 두고 희석만 걷어내는 것이 이 처리의 목적이다.

임계값을 바꾸면 지역 간 정책효과 비교가 깨진다. 지역을 추가·재적재할 때는 아파트 격자
비중이 일산 수준(약 38%)에 맞는지 확인하고 정할 것.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

#: 활동 격자로 인정할 연간 최소 단속 건수 (주 1회). 위 문서의 근거 참고.
ENFORCEMENT_MIN_PER_YEAR = 50


@dataclass(frozen=True)
class GridSelection:
    """선정 결과와 근거 — run.json에 남겨 적재본이 어떤 기준으로 만들어졌는지 추적한다."""

    grid_codes: list
    enforcement_min_per_year: int
    grids_before: int
    enforcement_retained_pct: float
    apartment_grid_share_pct: float

    def as_dict(self) -> dict[str, object]:
        return {
            "rule": f"아파트 ∪ 대기질 ∪ 단속 {self.enforcement_min_per_year}건 이상 격자",
            "enforcement_min_per_year": self.enforcement_min_per_year,
            "grids_before": self.grids_before,
            "grids_after": len(self.grid_codes),
            "enforcement_retained_pct": self.enforcement_retained_pct,
            "apartment_grid_share_pct": self.apartment_grid_share_pct,
        }


def select_active_grids(
    data: dict[str, pd.DataFrame], *, enforcement_min: int = ENFORCEMENT_MIN_PER_YEAR
) -> GridSelection:
    """아파트·대기질 격자는 무조건 남기고, 단속만 있는 격자는 건수 기준으로 거른다."""
    grids, enforcement = data["grids"], data["enforcement"]
    available = set(grids["grid_code"])
    keep = (set(data["apartments"]["grid_code"].dropna()) | set(data["air_quality"]["grid_code"].dropna())) & available

    counts = enforcement.loc[enforcement["grid_code"].isin(available)].groupby("grid_code").size()
    sparse_only = counts[~counts.index.isin(keep)]
    keep |= set(sparse_only[sparse_only >= enforcement_min].index)

    retained = enforcement["grid_code"].isin(keep).mean() * 100 if len(enforcement) else 0.0
    apartment_grids = set(data["apartments"]["grid_code"].dropna()) & keep
    return GridSelection(
        grid_codes=sorted(keep),
        enforcement_min_per_year=enforcement_min,
        grids_before=len(available),
        enforcement_retained_pct=round(float(retained), 1),
        apartment_grid_share_pct=round(len(apartment_grids) / max(len(keep), 1) * 100, 1),
    )


def apply_selection(data: dict[str, pd.DataFrame], selection: GridSelection) -> dict[str, pd.DataFrame]:
    """선정된 격자만 남긴 원천 묶음을 돌려준다 — 위험지수 정규화 모수가 여기서 결정된다."""
    keep = set(selection.grid_codes)
    return {name: frame.loc[frame["grid_code"].isin(keep)].copy() for name, frame in data.items()}
