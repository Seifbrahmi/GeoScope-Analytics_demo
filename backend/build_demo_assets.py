from __future__ import annotations

import io
import json
import re
import shutil
import sys
from calendar import monthrange
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from shapely.geometry import shape

from api import (
    AOD_OVERLAY_DIR,
    LAKE_CCI_OVERLAY_DIR,
    OVERLAY_DIR,
    app,
    build_aod_overlay,
    build_burned_area_overlay,
    build_lake_cci_overlay,
    build_lake_indicators,
    build_lake_selection_payload,
    build_lakes_geojson,
    build_lakes_overview_geojson,
    build_temperature_overlay,
    get_aod_legend,
    get_burned_area_legend,
    get_lake_cci_legend,
    get_temperature_legend,
    load_catchment_geometries,
    load_dataset,
    load_lakes_with_catchments,
)


BASE_DIR = Path(__file__).resolve().parent
DEMO_ASSETS_DIR = BASE_DIR / "demo_assets"
DEMO_OVERLAYS_DIR = DEMO_ASSETS_DIR / "overlays"
OVERLAY_INDEX_PATH = DEMO_ASSETS_DIR / "overlay-index.json"
LAKES_OVERVIEW_PATH = DEMO_ASSETS_DIR / "lakes-overview.geojson"
LAKE_SELECTION_INDEX_PATH = DEMO_ASSETS_DIR / "lake-selection-index.json"
LAKES_BY_CATCHMENT_PATH = DEMO_ASSETS_DIR / "lakes-by-catchment.json"
LAKE_SUMMARY_BY_CATCHMENT_PATH = DEMO_ASSETS_DIR / "lake-summary-by-catchment.json"
LAND_COVER_BY_CATCHMENT_PATH = DEMO_ASSETS_DIR / "land-cover-by-catchment.json"

MONTHS_2021 = [f"2021-{month:02d}" for month in range(1, 13)]
MONTH_KEY_COMPACT_RE = re.compile(r"^\d{6}$")

CATCHMENT_VARIABLES = {
    "burned_area": {
        "legend": get_burned_area_legend,
        "opacity": 0.8,
        "flag_key": "has_burned_data",
        "directory": OVERLAY_DIR,
    },
    "temperature": {
        "legend": get_temperature_legend,
        "opacity": 0.66,
        "flag_key": "has_temperature_data",
        "directory": OVERLAY_DIR,
    },
    "aod": {
        "legend": get_aod_legend,
        "opacity": 0.62,
        "flag_key": "has_aod_data",
        "directory": AOD_OVERLAY_DIR,
    },
}

LAKE_VARIABLES = {
    "chla": {
        "legend": lambda: get_lake_cci_legend("chla"),
        "opacity": 0.82,
        "flag_key": "has_data",
        "directory": LAKE_CCI_OVERLAY_DIR,
    },
    "lake_surface_water_temperature": {
        "legend": lambda: get_lake_cci_legend("lake_surface_water_temperature"),
        "opacity": 0.82,
        "flag_key": "has_data",
        "directory": LAKE_CCI_OVERLAY_DIR,
    },
    "tsm": {
        "legend": lambda: get_lake_cci_legend("tsm"),
        "opacity": 0.82,
        "flag_key": "has_data",
        "directory": LAKE_CCI_OVERLAY_DIR,
    },
}


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def reset_demo_assets() -> None:
    if DEMO_ASSETS_DIR.exists():
        shutil.rmtree(DEMO_ASSETS_DIR)
    DEMO_OVERLAYS_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def month_start_end(month_key: str) -> tuple[str, str]:
    year = int(month_key[:4])
    month = int(month_key[5:7])
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def month_compact(month_key: str) -> str:
    return month_key.replace("-", "")


def normalize_lake_id(value: Any) -> str:
    try:
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
    except (TypeError, ValueError):
        pass
    return str(value)


def build_lake_selection_index() -> dict[str, Any]:
    lakes_overview = build_lakes_overview_geojson()
    index: dict[str, Any] = {}
    for feature in lakes_overview.get("features", []):
        properties = feature.get("properties") or {}
        lake_id = properties.get("Lake_ID")
        if lake_id is None:
            continue
        normalized_lake_id = normalize_lake_id(lake_id)
        payload = build_lake_selection_payload(normalized_lake_id)
        if payload is not None:
            index[normalized_lake_id] = {
                "lake_id": payload.get("lake_id"),
                "catchment_id": payload.get("catchment_id"),
                "lake_label": payload.get("lake_label"),
            }
    return index


def build_lakes_by_catchment(lake_selection_index: dict[str, Any]) -> dict[str, Any]:
    catchment_ids = sorted(
        {
            str(payload["catchment_id"])
            for payload in lake_selection_index.values()
            if payload.get("catchment_id")
        }
    )
    return {catchment_id: build_lakes_geojson(catchment_id) for catchment_id in catchment_ids}


def build_lake_summaries(lake_selection_index: dict[str, Any]) -> dict[str, Any]:
    catchment_ids = sorted(
        {
            str(payload["catchment_id"])
            for payload in lake_selection_index.values()
            if payload.get("catchment_id")
        }
    )
    return {catchment_id: build_lake_indicators(catchment_id) for catchment_id in catchment_ids}


def build_land_cover_lookup(dataset: pd.DataFrame, lake_selection_index: dict[str, Any]) -> dict[str, Any]:
    catchment_ids = sorted(
        {
            str(payload["catchment_id"])
            for payload in lake_selection_index.values()
            if payload.get("catchment_id")
        }
    )
    lookup: dict[str, Any] = {}
    for catchment_id in catchment_ids:
        values = pd.to_numeric(
            dataset.loc[dataset["catchment_id"] == catchment_id, "land_cover"],
            errors="coerce",
        ).dropna()
        lookup[catchment_id] = int(values.mode().iloc[0]) if not values.empty else None
    return lookup


def build_bounds_payload(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    minx, miny, maxx, maxy = bounds
    return [[miny, minx], [maxy, maxx]]


def suppress_builder_output(callable_obj, *args, **kwargs):
    stream = io.StringIO()
    with redirect_stdout(stream):
        return callable_obj(*args, **kwargs)


def extract_filename(image_url: str | None) -> str | None:
    if not image_url:
        return None
    return str(image_url).rstrip("/").split("/")[-1]


def find_existing_monthly_catchment_png(variable_name: str, entity_id: str, month_key: str) -> Path | None:
    compact_month = month_compact(month_key)
    start_date = f"{compact_month}01"
    year = int(compact_month[:4])
    month = int(compact_month[4:6])
    end_date = f"{compact_month}{monthrange(year, month)[1]:02d}"

    if variable_name == "temperature":
        candidate = OVERLAY_DIR / f"temperature_{entity_id}_{start_date}_{end_date}.png"
        return candidate if candidate.exists() else None

    if variable_name == "aod":
        candidate = AOD_OVERLAY_DIR / f"aod_{entity_id}_{start_date}_{end_date}.png"
        return candidate if candidate.exists() else None

    return None


def find_existing_monthly_lake_png(variable_name: str, lake_id: str, month_key: str) -> Path | None:
    compact_month = month_compact(month_key)
    start_date = f"{compact_month}01"
    year = int(compact_month[:4])
    month = int(compact_month[4:6])
    end_date = f"{compact_month}{monthrange(year, month)[1]:02d}"
    candidate = LAKE_CCI_OVERLAY_DIR / f"{variable_name}_{lake_id}_{start_date}_{end_date}.png"
    return candidate if candidate.exists() else None


def build_target_filename(variable_name: str, entity_id: str, month_key: str) -> str:
    return f"{variable_name}_{entity_id}_{month_compact(month_key)}.png"


def copy_overlay(source_path: Path, target_filename: str) -> None:
    shutil.copy2(source_path, DEMO_OVERLAYS_DIR / target_filename)


def build_manifest_entry(
    target_filename: str,
    bounds: list[list[float]],
    legend: dict[str, Any],
    opacity: float,
    flag_key: str,
    source_mode: str,
    source_filename: str,
) -> dict[str, Any]:
    return {
        "image_url": f"/overlays/{target_filename}",
        "filename": target_filename,
        "bounds": bounds,
        "opacity": opacity,
        "legend": legend,
        flag_key: True,
        "source_mode": source_mode,
        "source_filename": source_filename,
    }


def build_catchment_overlay_payload(variable_name: str, catchment_id: str, start_date: str, end_date: str):
    overlay_builder = build_burned_area_overlay if variable_name == "burned_area" else (
        build_temperature_overlay if variable_name == "temperature" else build_aod_overlay
    )

    with app.test_request_context("/", base_url="http://demo.local"):
        return suppress_builder_output(
            overlay_builder,
            catchment_id,
            start_date,
            end_date,
        )


def build_lake_overlay_payload(variable_name: str, lake_id: str, start_date: str, end_date: str):
    with app.test_request_context("/", base_url="http://demo.local"):
        return suppress_builder_output(
            build_lake_cci_overlay,
            lake_id,
            variable_name,
            start_date,
            end_date,
            None,
        )


def generate_catchment_overlays(
    catchment_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {variable_name: {} for variable_name in CATCHMENT_VARIABLES}
    coverage: dict[str, Any] = {}

    for variable_name, config in CATCHMENT_VARIABLES.items():
        variable_stats = {
            "needed": len(catchment_ids) * len(MONTHS_2021),
            "available": 0,
            "reused": 0,
            "generated": 0,
            "missing": 0,
            "failed": 0,
        }
        legend = config["legend"]()

        for catchment_id in catchment_ids:
            month_entries: dict[str, Any] = {}

            for month_key in MONTHS_2021:
                target_filename = build_target_filename(variable_name, catchment_id, month_key)
                existing_png = find_existing_monthly_catchment_png(variable_name, catchment_id, month_key)
                start_date, end_date = month_start_end(month_key)

                try:
                    payload = build_catchment_overlay_payload(
                        variable_name,
                        catchment_id,
                        start_date,
                        end_date,
                    )
                except Exception:
                    payload = None
                    variable_stats["failed"] += 1

                if not payload:
                    variable_stats["missing"] += 1
                    continue

                source_filename = extract_filename(payload.get("image_url"))
                if not source_filename:
                    variable_stats["failed"] += 1
                    continue

                source_path = config["directory"] / source_filename
                if not source_path.exists():
                    variable_stats["failed"] += 1
                    continue

                demo_source_path = existing_png if existing_png is not None else source_path
                source_mode = "reused" if existing_png is not None else "generated"
                source_name = existing_png.name if existing_png is not None else source_filename

                copy_overlay(demo_source_path, target_filename)
                month_entries[month_key] = build_manifest_entry(
                    target_filename,
                    payload["bounds"],
                    legend,
                    config["opacity"],
                    config["flag_key"],
                    source_mode,
                    source_name,
                )
                variable_stats["available"] += 1
                variable_stats[source_mode] += 1

            if month_entries:
                manifest[variable_name][catchment_id] = month_entries

        coverage[variable_name] = variable_stats

    return manifest, coverage


def generate_lake_overlays(
    lakes_with_catchments: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {variable_name: {} for variable_name in LAKE_VARIABLES}
    coverage: dict[str, Any] = {}

    for variable_name, config in LAKE_VARIABLES.items():
        variable_stats = {
            "needed": int(len(lakes_with_catchments) * len(MONTHS_2021)),
            "available": 0,
            "reused": 0,
            "generated": 0,
            "missing": 0,
            "failed": 0,
        }
        legend = config["legend"]()

        for lake_row in lakes_with_catchments.itertuples(index=False):
            lake_id = normalize_lake_id(lake_row.Lake_ID)
            month_entries: dict[str, Any] = {}

            for month_key in MONTHS_2021:
                target_filename = build_target_filename(variable_name, lake_id, month_key)
                existing_png = find_existing_monthly_lake_png(variable_name, lake_id, month_key)
                start_date, end_date = month_start_end(month_key)

                try:
                    payload = build_lake_overlay_payload(
                        variable_name,
                        lake_id,
                        start_date,
                        end_date,
                    )
                except Exception:
                    payload = None
                    variable_stats["failed"] += 1

                if not payload:
                    variable_stats["missing"] += 1
                    continue

                source_filename = extract_filename(payload.get("image_url"))
                if not source_filename:
                    variable_stats["failed"] += 1
                    continue

                source_path = config["directory"] / source_filename
                if not source_path.exists():
                    variable_stats["failed"] += 1
                    continue

                demo_source_path = existing_png if existing_png is not None else source_path
                source_mode = "reused" if existing_png is not None else "generated"
                source_name = existing_png.name if existing_png is not None else source_filename

                copy_overlay(demo_source_path, target_filename)
                month_entries[month_key] = build_manifest_entry(
                    target_filename,
                    payload["bounds"],
                    legend,
                    config["opacity"],
                    config["flag_key"],
                    source_mode,
                    source_name,
                )
                variable_stats["available"] += 1
                variable_stats[source_mode] += 1

            if month_entries:
                manifest[variable_name][lake_id] = month_entries

        coverage[variable_name] = variable_stats

    return manifest, coverage


def calculate_asset_size() -> dict[str, Any]:
    overlay_files = list(DEMO_OVERLAYS_DIR.glob("*.png"))
    overlay_bytes = sum(file_path.stat().st_size for file_path in overlay_files)
    metadata_files = [path for path in DEMO_ASSETS_DIR.iterdir() if path.is_file()]
    metadata_bytes = sum(file_path.stat().st_size for file_path in metadata_files)
    total_bytes = overlay_bytes + metadata_bytes
    return {
        "overlay_file_count": len(overlay_files),
        "overlay_bytes": overlay_bytes,
        "metadata_bytes": metadata_bytes,
        "total_bytes": total_bytes,
    }


def main() -> None:
    ensure_stdout_utf8()
    reset_demo_assets()

    dataset = load_dataset().copy()
    dataset["date"] = pd.to_datetime(dataset["date"]).dt.to_period("M").dt.to_timestamp()
    dataset["catchment_id"] = dataset["catchment_id"].astype(str)

    lakes_overview = build_lakes_overview_geojson()
    lake_selection_index = build_lake_selection_index()
    lakes_by_catchment = build_lakes_by_catchment(lake_selection_index)
    lake_summaries = build_lake_summaries(lake_selection_index)
    land_cover_lookup = build_land_cover_lookup(dataset, lake_selection_index)

    lakes_with_catchments = load_lakes_with_catchments().copy()
    lakes_with_catchments = lakes_with_catchments[lakes_with_catchments["catchment_id"].notna()].copy()
    lakes_with_catchments["catchment_id"] = lakes_with_catchments["catchment_id"].astype(str)
    catchment_ids = sorted(set(lakes_with_catchments["catchment_id"].tolist()))

    catchment_manifest, catchment_coverage = generate_catchment_overlays(catchment_ids)
    lake_manifest, lake_coverage = generate_lake_overlays(lakes_with_catchments)

    overlay_index = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "year_months": MONTHS_2021,
            "reachable_lake_count": int(len(lakes_with_catchments)),
            "reachable_catchment_count": int(len(catchment_ids)),
            "generation_mode": "raster_faithful_monthly_cache",
        },
        "coverage": {
            "catchment": catchment_coverage,
            "lake": lake_coverage,
        },
        "catchment_overlays": catchment_manifest,
        "lake_overlays": lake_manifest,
    }

    write_json(OVERLAY_INDEX_PATH, overlay_index)
    write_json(LAKES_OVERVIEW_PATH, lakes_overview)
    write_json(LAKE_SELECTION_INDEX_PATH, lake_selection_index)
    write_json(LAKES_BY_CATCHMENT_PATH, lakes_by_catchment)
    write_json(LAKE_SUMMARY_BY_CATCHMENT_PATH, lake_summaries)
    write_json(LAND_COVER_BY_CATCHMENT_PATH, land_cover_lookup)

    asset_size = calculate_asset_size()
    print("Raster-faithful demo asset generation complete")
    print(json.dumps(overlay_index["coverage"], indent=2))
    print(json.dumps(asset_size, indent=2))


if __name__ == "__main__":
    with app.app_context():
        main()
