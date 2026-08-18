from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .grids import ENFORCEMENT_MIN_PER_YEAR, apply_selection, select_active_grids
from .manifest import InputManifest, manifest_sha256
from .oracle_loader import connect, rollback_active, stage_and_activate
from .quality import validate
from .risk import calculate_region_risk
from .transform import prepare_spatial_inputs


def _read_inputs(manifest: InputManifest, input_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {name: pd.read_csv(manifest.file(input_dir, name)) for name in manifest.files}
    air = frames["air_quality"]
    for column in ("no2", "co"):
        air[column] = pd.to_numeric(air[column], errors="coerce")
        air[column] = air.groupby(["region_code", "analysis_month", "hour_of_day"])[column].transform(
            lambda values: values.fillna(values.mean())
        )
        air[column] = air.groupby(["region_code", "analysis_month"])[column].transform(
            lambda values: values.fillna(values.mean())
        )
    return frames


def _run_id(region: str, year: int, source: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_source = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in source)[:30]
    return f"{region}-{year}-{safe_source}-{stamp}"


def build(manifest_path: Path, input_dir: Path, output_dir: Path, previous_metadata: Path | None,
          enforcement_min: int = ENFORCEMENT_MIN_PER_YEAR,
          allow_grid_reselection: bool = False) -> dict[str, object]:
    manifest = InputManifest.load(manifest_path)
    manifest.verify(input_dir)
    data = _read_inputs(manifest, input_dir)
    data = prepare_spatial_inputs(data, manifest.region_code, input_dir / "reference")
    # 격자 선정이 위험지수 정규화의 모수를 결정하므로 지오코딩 직후·위험지수 계산 직전에 한다
    selection = select_active_grids(data, enforcement_min=enforcement_min)
    data = apply_selection(data, selection)
    run_id = _run_id(manifest.region_code, manifest.analysis_year, manifest.source_version)
    risk = calculate_region_risk(
        region_code=manifest.region_code, analysis_year=manifest.analysis_year, pipeline_run_id=run_id,
        grids=data["grids"], enforcement=data["enforcement"], apartments=data["apartments"],
        air_quality=data["air_quality"],
    )
    previous_counts = None
    if previous_metadata is not None and previous_metadata.is_file():
        previous = json.loads(previous_metadata.read_text(encoding="utf-8"))
        previous_counts = previous.get("quality", {}).get("table_rows")
    report = validate(
        region_code=manifest.region_code, grids=data["grids"], apartments=data["apartments"],
        enforcement=data["enforcement"], air_quality=data["air_quality"], risk=risk,
        previous_table_rows=previous_counts, allow_row_delta=allow_grid_reselection,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, frame in data.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False)
    risk.to_csv(output_dir / "risk_index.csv", index=False, float_format="%.12f")
    metadata = {
        "pipeline_run_id": run_id, "region_code": manifest.region_code,
        "analysis_year": manifest.analysis_year, "source_version": manifest.source_version,
        "manifest_sha256": manifest_sha256(manifest_path), "quality": report.as_dict(),
        "grid_selection": selection.as_dict(),
    }
    (output_dir / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def _connection():
    required = ["ADB_USERNAME", "ADB_PASSWORD", "ADB_DSN", "ADB_WALLET_DIR", "ADB_WALLET_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError(f"ADB 환경변수 누락: {missing}")
    return connect(
        user=os.environ["ADB_USERNAME"], password=os.environ["ADB_PASSWORD"], dsn=os.environ["ADB_DSN"],
        wallet_dir=os.environ["ADB_WALLET_DIR"], wallet_password=os.environ["ADB_WALLET_PASSWORD"],
    )


def load(output_dir: Path) -> None:
    metadata = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    with _connection() as connection:
        stage_and_activate(
            connection, run_id=metadata["pipeline_run_id"], region_code=metadata["region_code"],
            analysis_year=metadata["analysis_year"], input_version=metadata["source_version"],
            manifest_sha256=metadata["manifest_sha256"], quality_report=metadata["quality"],
            grids_csv=output_dir / "grids.csv", apartments_csv=output_dir / "apartments.csv",
            enforcement_csv=output_dir / "enforcement.csv", air_csv=output_dir / "air_quality.csv",
            risk_csv=output_dir / "risk_index.csv",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="CoolingVerse 지역 격리 데이터 파이프라인")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-manifest")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--input-dir", type=Path, required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--manifest", type=Path, required=True)
    build_parser.add_argument("--input-dir", type=Path, required=True)
    build_parser.add_argument("--output-dir", type=Path, required=True)
    build_parser.add_argument("--previous-metadata", type=Path)
    build_parser.add_argument("--enforcement-min", type=int, default=ENFORCEMENT_MIN_PER_YEAR,
                              help="활동 격자로 인정할 연간 최소 단속 건수 (기본 %(default)s)")
    build_parser.add_argument("--allow-grid-reselection", action="store_true",
                              help="격자 기준 변경으로 행 수가 크게 바뀌는 것을 승인한다 "
                                   "(직전 승인본 대비 ±5% 게이트를 경고로 낮춤)")
    load_parser = sub.add_parser("load")
    load_parser.add_argument("--output-dir", type=Path, required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--region", required=True, choices=["pangyo", "bucheon", "pyeongchon"])
    rollback.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    if args.command == "verify-manifest":
        manifest = InputManifest.load(args.manifest)
        manifest.verify(args.input_dir)
        print(json.dumps({"verified": True, "region_code": manifest.region_code}))
    elif args.command == "build":
        print(json.dumps(build(args.manifest, args.input_dir, args.output_dir, args.previous_metadata,
                               args.enforcement_min, args.allow_grid_reselection), ensure_ascii=False))
    elif args.command == "load":
        load(args.output_dir)
    else:
        with _connection() as connection:
            rollback_active(connection, region_code=args.region, analysis_year=args.year)


if __name__ == "__main__":
    main()
