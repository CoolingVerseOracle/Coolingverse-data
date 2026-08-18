from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InputManifest:
    region_code: str
    analysis_year: int
    source_version: str
    files: dict[str, dict[str, str]]

    @classmethod
    def load(cls, path: Path) -> InputManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        region = raw["region_code"]
        if region not in {"pangyo", "bucheon", "pyeongchon"}:
            raise ValueError(f"지원하지 않는 활성 지역: {region}")
        return cls(region, int(raw["analysis_year"]), raw["source_version"], raw["files"])

    def verify(self, input_dir: Path) -> None:
        required = {"grids", "enforcement", "apartments", "air_quality"}
        missing = required - self.files.keys()
        if missing:
            raise ValueError(f"manifest 필수 파일 누락: {sorted(missing)}")
        for name, info in self.files.items():
            path = input_dir / info["path"]
            if not path.is_file():
                raise FileNotFoundError(f"{name}: {path}")
            actual = sha256_file(path)
            if actual.lower() != info["sha256"].lower():
                raise ValueError(f"SHA-256 불일치: {name} expected={info['sha256']} actual={actual}")

    def file(self, input_dir: Path, name: str) -> Path:
        return input_dir / self.files[name]["path"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(path: Path) -> str:
    return sha256_file(path)
