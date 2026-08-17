from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path


class RegionalGeocodeCache:
    """주소 결과를 지역별 파일로 분리해 다른 지역 검색 결과 재사용을 막는다."""

    def __init__(self, cache_root: Path, region_code: str) -> None:
        self.path = cache_root / region_code / "geocode-cache" / "cache.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.values: dict[str, dict[str, float] | None] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )

    def resolve(self, address: str, geocoder: Callable[[str], tuple[float, float] | None]) -> tuple[float, float] | None:
        key = " ".join(address.split())
        if key not in self.values:
            found = geocoder(key)
            self.values[key] = None if found is None else {"lat": found[0], "lng": found[1]}
            self.path.write_text(json.dumps(self.values, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        value = self.values[key]
        return None if value is None else (float(value["lat"]), float(value["lng"]))
