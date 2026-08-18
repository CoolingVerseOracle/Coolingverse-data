from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree

from .geocode import RegionalGeocodeCache


def prepare_spatial_inputs(data: dict[str, pd.DataFrame], region_code: str, cache_root: Path) -> dict[str, pd.DataFrame]:
    """지오코딩과 격자 매핑을 한 지역의 좌표·캐시 안에서만 수행한다."""
    grids = data["grids"].copy()
    _require_single_region(grids, region_code, "grids")
    cache = RegionalGeocodeCache(cache_root, region_code)
    for name, address_column in (("enforcement", "place_text"), ("apartments", "address")):
        frame = data[name].copy()
        _require_single_region(frame, region_code, name)
        frame = _geocode_missing(frame, address_column, cache, region_code)
        data[name] = map_nearest_grid(frame, grids)
    data["air_quality"] = map_nearest_grid(data["air_quality"].copy(), grids)
    return data


def map_nearest_grid(frame: pd.DataFrame, grids: pd.DataFrame) -> pd.DataFrame:
    if "grid_code" not in frame:
        frame["grid_code"] = None
    missing = frame["grid_code"].isna() & frame["lat"].notna() & frame["lng"].notna()
    if not missing.any():
        return frame
    tree = cKDTree(grids[["center_lat", "center_lng"]].to_numpy(float))
    points = frame.loc[missing, ["lat", "lng"]].to_numpy(float)
    distances, indices = tree.query(points, k=1)
    # 잘못된 타 지역 좌표를 가장자리 격자에 억지로 붙이지 않는다(약 3km 이상 거부).
    accepted = np.asarray(distances) <= 0.03
    target_indices = frame.index[missing]
    mapped_codes = grids.iloc[np.asarray(indices)]["grid_code"].to_numpy(object)
    frame.loc[target_indices[accepted], "grid_code"] = mapped_codes[accepted]
    return frame


def _geocode_missing(
    frame: pd.DataFrame, address_column: str, cache: RegionalGeocodeCache, region_code: str,
) -> pd.DataFrame:
    if address_column not in frame or "lat" not in frame or "lng" not in frame:
        return frame
    missing = frame["lat"].isna() | frame["lng"].isna()
    if not missing.any():
        return frame
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        return frame
    display = {"pangyo": "성남시 분당구", "bucheon": "부천시", "pyeongchon": "안양시 동안구"}[region_code]

    def kakao(address: str) -> tuple[float, float] | None:
        response = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": f"{display} {address}"},
            headers={"Authorization": f"KakaoAK {api_key}"}, timeout=10,
        )
        response.raise_for_status()
        documents = response.json().get("documents", [])
        return None if not documents else (float(documents[0]["y"]), float(documents[0]["x"]))

    for index, address in frame.loc[missing, address_column].dropna().items():
        found = cache.resolve(str(address), kakao)
        if found is not None:
            frame.loc[index, ["lat", "lng"]] = found
    return frame


def _require_single_region(frame: pd.DataFrame, region: str, name: str) -> None:
    if "region_code" not in frame or set(frame["region_code"].dropna().astype(str).unique()) != {region}:
        raise ValueError(f"{name}: 지역 누락 또는 혼입")
