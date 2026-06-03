from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
from shapely.geometry import MultiPolygon, Polygon, shape

from api import (
    app,
    build_lake_indicators,
    build_lake_selection_payload,
    build_lakes_geojson,
    build_lakes_overview_geojson,
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

CANVAS_SIZE = 512
CANVAS_PADDING = 18

CATCHMENT_OVERLAY_CONFIG = {
    "burned_area": {
        "legend": get_burned_area_legend,
        "opacity": 0.8,
        "flag_key": "has_burned_data",
        "min_value": 0.0,
    },
    "temperature": {
        "legend": get_temperature_legend,
        "opacity": 0.66,
        "flag_key": "has_temperature_data",
        "min_value": None,
    },
    "aod": {
        "legend": get_aod_legend,
        "opacity": 0.62,
        "flag_key": "has_aod_data",
        "min_value": None,
    },
}

LAKE_OVERLAY_CONFIG = {
    "chla": {
        "legend": lambda: get_lake_cci_legend("chla"),
        "opacity": 0.82,
        "flag_key": "has_data",
        "min_value": None,
    },
    "lake_surface_water_temperature": {
        "legend": lambda: get_lake_cci_legend("lake_surface_water_temperature"),
        "opacity": 0.82,
        "flag_key": "has_data",
        "min_value": None,
    },
    "tsm": {
        "legend": lambda: get_lake_cci_legend("tsm"),
        "opacity": 0.82,
        "flag_key": "has_data",
        "min_value": None,
    },
}


def ensure_directories() -> None:
    DEMO_OVERLAYS_DIR.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_color(color_value: str | list[int]) -> tuple[int, int, int]:
    if isinstance(color_value, str):
        normalized = color_value.lstrip("#")
        return (
            int(normalized[0:2], 16),
            int(normalized[2:4], 16),
            int(normalized[4:6], 16),
        )
    return (int(color_value[0]), int(color_value[1]), int(color_value[2]))


def interpolate_color(colors: list[tuple[int, int, int]], ratio: float) -> tuple[int, int, int]:
    if len(colors) == 1:
        return colors[0]

    clamped = max(0.0, min(1.0, ratio))
    scaled = clamped * (len(colors) - 1)
    left_index = int(np.floor(scaled))
    right_index = min(left_index + 1, len(colors) - 1)
    blend = scaled - left_index
    left = np.array(colors[left_index], dtype=np.float32)
    right = np.array(colors[right_index], dtype=np.float32)
    blended = left * (1.0 - blend) + right * blend
    return tuple(int(value) for value in blended.tolist())


def compute_value_ranges(dataset: pd.DataFrame, catchment_ids: set[str], lake_catchment_ids: set[str]) -> dict[str, tuple[float, float]]:
    ranges: dict[str, tuple[float, float]] = {}

    for variable_name in CATCHMENT_OVERLAY_CONFIG:
        values = pd.to_numeric(
            dataset.loc[dataset["catchment_id"].isin(catchment_ids), variable_name],
            errors="coerce",
        ).dropna()
        if variable_name == "burned_area":
            values = values[values > 0]
        if values.empty:
            ranges[variable_name] = (0.0, 1.0)
            continue
        lower = float(values.quantile(0.05))
        upper = float(values.quantile(0.95))
        if upper <= lower:
            lower = float(values.min())
            upper = float(values.max())
        if upper <= lower:
            upper = lower + 1.0
        ranges[variable_name] = (lower, upper)

    for variable_name in LAKE_OVERLAY_CONFIG:
        values = pd.to_numeric(
            dataset.loc[dataset["catchment_id"].isin(lake_catchment_ids), variable_name],
            errors="coerce",
        ).dropna()
        if values.empty:
            ranges[variable_name] = (0.0, 1.0)
            continue
        lower = float(values.quantile(0.05))
        upper = float(values.quantile(0.95))
        if upper <= lower:
            lower = float(values.min())
            upper = float(values.max())
        if upper <= lower:
            upper = lower + 1.0
        ranges[variable_name] = (lower, upper)

    return ranges


def normalize_value(value: float, value_range: tuple[float, float]) -> float:
    lower, upper = value_range
    if upper <= lower:
        return 0.5
    return max(0.0, min(1.0, (float(value) - lower) / (upper - lower)))


def iter_polygons(geometry: Polygon | MultiPolygon) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            yield polygon


def project_point(x_value: float, y_value: float, bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    minx, miny, maxx, maxy = bounds
    width = max(maxx - minx, 1e-9)
    height = max(maxy - miny, 1e-9)
    usable_width = CANVAS_SIZE - (2 * CANVAS_PADDING)
    usable_height = CANVAS_SIZE - (2 * CANVAS_PADDING)
    x_ratio = (x_value - minx) / width
    y_ratio = (maxy - y_value) / height
    return (
        CANVAS_PADDING + (x_ratio * usable_width),
        CANVAS_PADDING + (y_ratio * usable_height),
    )


def build_mask(geometry: Polygon | MultiPolygon, bounds: tuple[float, float, float, float]) -> Image.Image:
    mask_image = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    draw = ImageDraw.Draw(mask_image)

    for polygon in iter_polygons(geometry):
        exterior = [project_point(x_value, y_value, bounds) for x_value, y_value in polygon.exterior.coords]
        draw.polygon(exterior, fill=255)
        for interior in polygon.interiors:
            hole = [project_point(x_value, y_value, bounds) for x_value, y_value in interior.coords]
            draw.polygon(hole, fill=0)

    return mask_image


def render_overlay_image(
    geometry: Polygon | MultiPolygon,
    ratio: float,
    colors: list[str | list[int]],
    opacity: float,
) -> Image.Image:
    bounds = geometry.bounds
    mask = build_mask(geometry, bounds)
    palette = [parse_color(color_value) for color_value in colors]
    base_color = interpolate_color(palette, ratio)

    rgba = np.zeros((CANVAS_SIZE, CANVAS_SIZE, 4), dtype=np.uint8)
    x_gradient = np.linspace(0.78, 1.0, CANVAS_SIZE, dtype=np.float32)
    y_gradient = np.linspace(1.0, 0.84, CANVAS_SIZE, dtype=np.float32)
    combined_gradient = np.outer(y_gradient, x_gradient)

    for channel_index, channel_value in enumerate(base_color):
        channel = np.clip(channel_value * combined_gradient, 0, 255)
        rgba[..., channel_index] = channel.astype(np.uint8)

    alpha_base = int(255 * opacity)
    mask_array = np.array(mask, dtype=np.float32) / 255.0
    alpha_gradient = np.clip((0.62 + (0.38 * combined_gradient)) * mask_array, 0.0, 1.0)
    rgba[..., 3] = np.clip(alpha_base * alpha_gradient, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def save_overlay_image(image: Image.Image, filename: str) -> None:
    image.save(DEMO_OVERLAYS_DIR / filename, optimize=True)


def build_overlay_payload(filename: str, bounds: tuple[float, float, float, float], legend: dict[str, Any], opacity: float, flag_key: str) -> dict[str, Any]:
    minx, miny, maxx, maxy = bounds
    return {
        "image_url": f"/overlays/{filename}",
        "filename": filename,
        "bounds": [[miny, minx], [maxy, maxx]],
        "opacity": opacity,
        "legend": legend,
        flag_key: True,
    }


def build_month_key(date_value: pd.Timestamp) -> str:
    return pd.Timestamp(date_value).strftime("%Y-%m")


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


def generate_catchment_overlays(
    dataset: pd.DataFrame,
    reachable_catchment_ids: list[str],
    value_ranges: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    catchment_geometries = {
        catchment_id: shape(geometry_json)
        for catchment_id, geometry_json in load_catchment_geometries().items()
        if catchment_id in reachable_catchment_ids
    }
    overlay_index: dict[str, Any] = {}

    for variable_name, config in CATCHMENT_OVERLAY_CONFIG.items():
        legend = config["legend"]()
        overlay_index[variable_name] = {}

        for catchment_id in reachable_catchment_ids:
            geometry = catchment_geometries.get(catchment_id)
            if geometry is None or geometry.is_empty:
                continue

            monthly_rows = dataset[dataset["catchment_id"] == catchment_id].copy()
            if monthly_rows.empty:
                continue

            month_entries: dict[str, Any] = {}
            for row in monthly_rows.itertuples(index=False):
                raw_value = getattr(row, variable_name)
                numeric_value = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
                if pd.isna(numeric_value):
                    continue
                if config["min_value"] is not None and float(numeric_value) <= float(config["min_value"]):
                    continue

                month_key = build_month_key(row.date)
                ratio = normalize_value(float(numeric_value), value_ranges[variable_name])
                filename = f"{variable_name}_{catchment_id}_{month_key.replace('-', '')}.png"
                image = render_overlay_image(geometry, ratio, legend["colors"], config["opacity"])
                save_overlay_image(image, filename)
                month_entries[month_key] = build_overlay_payload(
                    filename,
                    geometry.bounds,
                    legend,
                    config["opacity"],
                    config["flag_key"],
                )

            if month_entries:
                overlay_index[variable_name][catchment_id] = month_entries

    return overlay_index


def generate_lake_overlays(
    dataset: pd.DataFrame,
    lakes_with_catchments: pd.DataFrame,
    value_ranges: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    overlay_index: dict[str, Any] = {}

    for variable_name, config in LAKE_OVERLAY_CONFIG.items():
        legend = config["legend"]()
        overlay_index[variable_name] = {}

        for lake_row in lakes_with_catchments.itertuples(index=False):
            lake_id = normalize_lake_id(lake_row.Lake_ID)
            catchment_id = getattr(lake_row, "catchment_id", None)
            geometry = getattr(lake_row, "geometry", None)
            if not catchment_id or geometry is None or geometry.is_empty:
                continue

            monthly_rows = dataset[dataset["catchment_id"] == str(catchment_id)].copy()
            if monthly_rows.empty:
                continue

            month_entries: dict[str, Any] = {}
            for row in monthly_rows.itertuples(index=False):
                raw_value = getattr(row, variable_name)
                numeric_value = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
                if pd.isna(numeric_value):
                    continue

                month_key = build_month_key(row.date)
                ratio = normalize_value(float(numeric_value), value_ranges[variable_name])
                filename = f"{variable_name}_{lake_id}_{month_key.replace('-', '')}.png"
                image = render_overlay_image(geometry, ratio, legend["colors"], config["opacity"])
                save_overlay_image(image, filename)
                month_entries[month_key] = build_overlay_payload(
                    filename,
                    geometry.bounds,
                    legend,
                    config["opacity"],
                    config["flag_key"],
                )

            if month_entries:
                overlay_index[variable_name][lake_id] = month_entries

    return overlay_index


def build_overlay_index(dataset: pd.DataFrame) -> dict[str, Any]:
    lakes_with_catchments = load_lakes_with_catchments().copy()
    lakes_with_catchments = lakes_with_catchments[lakes_with_catchments["catchment_id"].notna()].copy()
    lakes_with_catchments["catchment_id"] = lakes_with_catchments["catchment_id"].astype(str)

    reachable_catchment_ids = sorted(set(lakes_with_catchments["catchment_id"].tolist()))
    lake_catchment_ids = set(reachable_catchment_ids)
    value_ranges = compute_value_ranges(dataset, set(reachable_catchment_ids), lake_catchment_ids)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "reachable_lake_count": int(len(lakes_with_catchments)),
            "reachable_catchment_count": int(len(reachable_catchment_ids)),
            "month_count": int(dataset["date"].nunique()),
            "months": sorted(dataset["date"].dt.strftime("%Y-%m").unique().tolist()),
            "generation_mode": "geometry_png_demo_assets",
        },
        "value_ranges": {
            variable_name: {"min": value_range[0], "max": value_range[1]}
            for variable_name, value_range in value_ranges.items()
        },
        "catchment_overlays": generate_catchment_overlays(dataset, reachable_catchment_ids, value_ranges),
        "lake_overlays": generate_lake_overlays(dataset, lakes_with_catchments, value_ranges),
    }


def main() -> None:
    ensure_directories()
    dataset = load_dataset().copy()
    dataset["date"] = pd.to_datetime(dataset["date"]).dt.to_period("M").dt.to_timestamp()
    dataset["catchment_id"] = dataset["catchment_id"].astype(str)

    overlay_index = build_overlay_index(dataset)
    lakes_overview = build_lakes_overview_geojson()
    lake_selection_index = build_lake_selection_index()
    lakes_by_catchment = build_lakes_by_catchment(lake_selection_index)
    lake_summaries = build_lake_summaries(lake_selection_index)
    land_cover_lookup = build_land_cover_lookup(dataset, lake_selection_index)

    write_json(OVERLAY_INDEX_PATH, overlay_index)
    write_json(LAKES_OVERVIEW_PATH, lakes_overview)
    write_json(LAKE_SELECTION_INDEX_PATH, lake_selection_index)
    write_json(LAKES_BY_CATCHMENT_PATH, lakes_by_catchment)
    write_json(LAKE_SUMMARY_BY_CATCHMENT_PATH, lake_summaries)
    write_json(LAND_COVER_BY_CATCHMENT_PATH, land_cover_lookup)

    print("Demo asset generation complete")
    print(f"Overlay manifest: {OVERLAY_INDEX_PATH}")
    print(f"Overlay files: {DEMO_OVERLAYS_DIR}")
    print(f"Lakes overview features: {len(lakes_overview.get('features', []))}")
    print(f"Lake selection index: {len(lake_selection_index)}")


if __name__ == "__main__":
    with app.app_context():
        main()
