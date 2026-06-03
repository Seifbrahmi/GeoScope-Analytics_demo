import os

from flask import Flask, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
from functools import lru_cache
from pathlib import Path
import json
import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    import rasterio
    from PIL import Image
    from rasterio.mask import mask
    from rasterio.transform import array_bounds
    from rasterio.warp import transform, transform_bounds, transform_geom
    from shapely.geometry import box, shape
    GEOSPATIAL_RUNTIME_AVAILABLE = True
except ImportError:
    gpd = None
    rasterio = None
    Image = None
    mask = None
    array_bounds = None
    transform = None
    transform_bounds = None
    transform_geom = None
    box = None
    shape = None
    GEOSPATIAL_RUNTIME_AVAILABLE = False

try:
    from temporal_resampling import normalize_aggregation_mode, resample_analysis_records
except ImportError:
    from backend.temporal_resampling import normalize_aggregation_mode, resample_analysis_records


app = Flask(__name__)


def parse_cors_origins():
    configured_origins = os.getenv("ALLOWED_ORIGINS")
    if configured_origins:
        origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
        return origins or ["*"]

    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ]


CORS(app, resources={
    r"/*": {
        "origins": parse_cors_origins()
    }
})

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATASET_PATH = Path(__file__).resolve().parent / "outputs" / "final_dataset.csv"
DEMO_ASSETS_DIR = Path(__file__).resolve().parent / "demo_assets"
DEMO_OVERLAYS_DIR = DEMO_ASSETS_DIR / "overlays"
DEMO_OVERLAY_INDEX_PATH = DEMO_ASSETS_DIR / "overlay-index.json"
DEMO_LAKES_OVERVIEW_PATH = DEMO_ASSETS_DIR / "lakes-overview.geojson"
DEMO_LAKE_SELECTION_INDEX_PATH = DEMO_ASSETS_DIR / "lake-selection-index.json"
DEMO_LAKES_BY_CATCHMENT_PATH = DEMO_ASSETS_DIR / "lakes-by-catchment.json"
DEMO_LAKE_SUMMARY_BY_CATCHMENT_PATH = DEMO_ASSETS_DIR / "lake-summary-by-catchment.json"
DEMO_LAND_COVER_BY_CATCHMENT_PATH = DEMO_ASSETS_DIR / "land-cover-by-catchment.json"
OVERLAY_DIR = Path(__file__).resolve().parent / "outputs" / "burned_overlays"
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
AOD_OVERLAY_DIR = Path(__file__).resolve().parent / "outputs" / "aod_overlays"
AOD_OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
LAKE_CCI_OVERLAY_DIR = Path(__file__).resolve().parent / "outputs" / "lake_cci_overlays"
LAKE_CCI_OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
MAX_OVERLAY_DIMENSION = 1600
CATCHMENTS_PATH = BASE_DIR / "frontend" / "data" / "catchments_aoi.geojson"
CATCHMENT_ID_MAP_PATH = BASE_DIR / "frontend" / "data" / "catchment-id-map.json"
LAKE_SIMPLIFY_TOLERANCE = 0.001
BURNED_PIXEL_THRESHOLD = 0.0
SUPPORTED_RESULT_VARIABLES = {
    "burned_area",
    "rainfall",
    "temperature",
    "aod",
    "chla",
    "lake_surface_water_temperature",
    "tsm",
}
DEFAULT_RESULT_VARIABLES = [
    "burned_area",
    "rainfall",
    "temperature",
    "aod",
    "chla",
    "lake_surface_water_temperature",
    "tsm",
]


def load_dataset():
    dataset = pd.read_csv(DATASET_PATH)
    dataset["date"] = pd.to_datetime(dataset["date"])
    dataset["catchment_id"] = dataset["catchment_id"].astype(str)

    numeric_defaults = {
        "burned_area": 0.0,
        "temperature": pd.NA,
        "aod": pd.NA,
        "chla": pd.NA,
        "lake_surface_water_temperature": pd.NA,
        "tsm": pd.NA,
        "land_cover": pd.NA,
    }

    for column_name, default_value in numeric_defaults.items():
        if column_name in dataset.columns:
            dataset[column_name] = pd.to_numeric(dataset[column_name], errors="coerce")
        else:
            dataset[column_name] = default_value

    print("Dataset columns:", dataset.columns.tolist())
    print(dataset.head())
    return dataset


@lru_cache(maxsize=1)
def load_demo_overlay_index():
    if not DEMO_OVERLAY_INDEX_PATH.exists():
        return {}

    with DEMO_OVERLAY_INDEX_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def require_geospatial_runtime():
    if not GEOSPATIAL_RUNTIME_AVAILABLE:
        raise RuntimeError(
            "Optional geospatial dependencies are unavailable in this runtime. "
            "Use the pre-generated demo assets instead of runtime raster processing."
        )


def legacy_data_path(*parts: str):
    require_geospatial_runtime()
    return BASE_DIR.joinpath("data", *parts)


def load_json_file(path: Path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def load_demo_lakes_overview():
    return load_json_file(DEMO_LAKES_OVERVIEW_PATH, {"type": "FeatureCollection", "features": []})


@lru_cache(maxsize=1)
def load_demo_lake_selection_index():
    return load_json_file(DEMO_LAKE_SELECTION_INDEX_PATH, {})


@lru_cache(maxsize=1)
def load_demo_lakes_by_catchment():
    return load_json_file(DEMO_LAKES_BY_CATCHMENT_PATH, {})


@lru_cache(maxsize=1)
def load_demo_lake_summary_by_catchment():
    return load_json_file(DEMO_LAKE_SUMMARY_BY_CATCHMENT_PATH, {})


@lru_cache(maxsize=1)
def load_demo_land_cover_by_catchment():
    return load_json_file(DEMO_LAND_COVER_BY_CATCHMENT_PATH, {})


def get_demo_lake_feature(lake_id: str):
    normalized_lake_id = normalize_lake_id(lake_id)
    for feature in load_demo_lakes_overview().get("features", []):
        properties = feature.get("properties") or {}
        feature_lake_id = normalize_lake_id(properties.get("Lake_ID"))
        if feature_lake_id == normalized_lake_id:
            return feature
    return None


def get_demo_catchment_feature(catchment_id: str):
    if not catchment_id:
        return None

    geometry = load_catchment_geometries().get(str(catchment_id))
    if not geometry:
        return None

    return {
        "type": "Feature",
        "properties": {"catchment_id": str(catchment_id)},
        "geometry": geometry,
    }


def get_demo_lake_indicators(catchment_id: str):
    summary = load_demo_lake_summary_by_catchment().get(str(catchment_id))
    if summary is not None:
        return summary

    return {
        "lake_coverage_percent": 0.0,
        "water_insight": "Analysis unavailable"
    }


def serialize_records(frame: pd.DataFrame, aggregation: str = "monthly"):
    records = frame.copy()
    resolved_aggregation = normalize_aggregation_mode(aggregation)

    if "date" in records.columns:
        date_format = "%Y-%m" if resolved_aggregation == "monthly" else "%Y-%m-%d"
        records["date"] = pd.to_datetime(records["date"]).dt.strftime(date_format)

    # Replace invalid numeric values
    records = records.replace([np.inf, -np.inf], np.nan)

    # Convert ALL NaN/NaT values to Python None
    records = records.astype(object).where(pd.notnull(records), None)

    # Safe integer conversion
    if "land_cover" in records.columns:
        records["land_cover"] = records["land_cover"].apply(
            lambda value: None if value is None else int(value)
        )

    return records.to_dict(orient="records")


def parse_requested_variables(raw_value: str | None):
    if not raw_value:
        return DEFAULT_RESULT_VARIABLES.copy()

    requested_variables = []
    for variable in raw_value.split(","):
        normalized = variable.strip().lower()
        if normalized in SUPPORTED_RESULT_VARIABLES and normalized not in requested_variables:
            requested_variables.append(normalized)

    return requested_variables or DEFAULT_RESULT_VARIABLES.copy()


@lru_cache(maxsize=1)
def load_aoi_gdf():
    require_geospatial_runtime()
    aoi_path = legacy_data_path("AOI.geojson")
    if not aoi_path.exists():
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    aoi_gdf = gpd.read_file(aoi_path)
    if aoi_gdf.crs is None:
        aoi_gdf = aoi_gdf.set_crs(epsg=4326)
    elif aoi_gdf.crs.to_epsg() != 4326:
        aoi_gdf = aoi_gdf.to_crs(epsg=4326)

    return aoi_gdf[["geometry"]].copy()


@lru_cache(maxsize=1)
def load_catchment_geometries():
    if not CATCHMENTS_PATH.exists() or not CATCHMENT_ID_MAP_PATH.exists():
        return {}

    with CATCHMENT_ID_MAP_PATH.open("r", encoding="utf-8") as file:
        outlet_to_catchment = {
            str(outlet_id): str(catchment_id)
            for outlet_id, catchment_id in json.load(file).items()
        }

    with CATCHMENTS_PATH.open("r", encoding="utf-8") as file:
        geojson = json.load(file)

    geometries = {}
    for feature in geojson.get("features", []):
        properties = feature.get("properties") or {}
        outlet_id = properties.get("Outlet_id")
        if outlet_id is None:
            continue

        catchment_id = outlet_to_catchment.get(str(outlet_id))
        geometry = feature.get("geometry")
        if catchment_id and geometry:
            geometries[catchment_id] = geometry

    return geometries


@lru_cache(maxsize=1)
def load_catchments_gdf():
    require_geospatial_runtime()
    geometries = load_catchment_geometries()
    if not geometries:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    catchments = gpd.GeoDataFrame(
        [
            {"catchment_id": catchment_id, "geometry": shape(geometry)}
            for catchment_id, geometry in geometries.items()
        ],
        geometry="geometry",
        crs="EPSG:4326"
    )

    aoi_gdf = load_aoi_gdf()
    if not aoi_gdf.empty:
        aoi_shape = aoi_gdf.union_all()
        catchments = catchments[catchments.geometry.intersects(aoi_shape)].copy()

    return catchments


@lru_cache(maxsize=1)
def load_lakes_dataset():
    require_geospatial_runtime()
    lakes_path = legacy_data_path("LakesOI.geojson")
    if not lakes_path.exists():
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    lakes_gdf = gpd.read_file(lakes_path)
    if lakes_gdf.crs is None:
        lakes_gdf = lakes_gdf.set_crs(epsg=4326)
    elif lakes_gdf.crs.to_epsg() != 4326:
        lakes_gdf = lakes_gdf.to_crs(epsg=4326)

    aoi_gdf = load_aoi_gdf()
    if not aoi_gdf.empty:
        aoi_shape = aoi_gdf.union_all()
        lakes_gdf = lakes_gdf[lakes_gdf.geometry.intersects(aoi_shape)].copy()

    if not lakes_gdf.empty:
        lakes_gdf["geometry"] = lakes_gdf.geometry.simplify(
            LAKE_SIMPLIFY_TOLERANCE,
            preserve_topology=True
        )
        lakes_gdf = lakes_gdf[~lakes_gdf.geometry.is_empty].copy()

    return lakes_gdf


@lru_cache(maxsize=1)
def load_lakes_with_catchments():
    require_geospatial_runtime()
    lakes_gdf = load_lakes_dataset().copy()
    catchments_gdf = load_catchments_gdf()

    if lakes_gdf.empty or catchments_gdf.empty:
        lakes_gdf["catchment_id"] = None
        return lakes_gdf

    lake_points = lakes_gdf[["Lake_ID", "geometry"]].copy()
    lake_points["geometry"] = lake_points.geometry.representative_point()
    joined = gpd.sjoin(
        lake_points,
        catchments_gdf[["catchment_id", "geometry"]],
        how="left",
        predicate="within"
    )

    lakes_gdf["catchment_id"] = joined["catchment_id"].astype("string").where(joined["catchment_id"].notna(), None)
    return lakes_gdf


def month_start_range(start_date: str, end_date: str):
    start = pd.to_datetime(start_date).to_period("M").to_timestamp()
    end = pd.to_datetime(end_date).to_period("M").to_timestamp()
    return pd.date_range(start=start, end=end, freq="MS")


def get_firecci_confidence_path(month_start: pd.Timestamp):
    filename = f"{month_start.strftime('%Y%m01')}-ESACCI-L3S_FIRE-BA-MODIS-AREA_1-fv5.1-CL.tif"
    path = legacy_data_path("firecci", filename)
    return path if path.exists() else None


def get_temperature_raster_path(month_start: pd.Timestamp):
    year = month_start.strftime("%Y")
    month = month_start.strftime("%m")
    # Normalize monthly ERA5 temperature filenames automatically.
    candidates = sorted(legacy_data_path("ERA5_Temperature").glob(f"*_{year}_{month}.tif"))
    return candidates[0] if candidates else None


def get_aod_raster_path(month_start: pd.Timestamp):
    year = month_start.strftime("%Y")
    month = month_start.strftime("%m")
    candidates = sorted(legacy_data_path("AOD_Exports").glob(f"*_{year}_{month}.tif"))
    return candidates[0] if candidates else None


def get_lake_cci_netcdf_path(day_timestamp: pd.Timestamp):
    date_key = day_timestamp.strftime("%Y%m%d")
    candidates = sorted(legacy_data_path("lake_cci").glob(f"*{date_key}*_processed.nc"))
    return candidates[0] if candidates else None


def colorize_burned_area(confidence_grid: np.ndarray):
    rgba = np.zeros((confidence_grid.shape[0], confidence_grid.shape[1], 4), dtype=np.uint8)
    valid_mask = np.isfinite(confidence_grid) & (confidence_grid > 0)

    if not np.any(valid_mask):
        return rgba

    values = confidence_grid[valid_mask].astype(np.float32)
    lower = float(np.percentile(values, 5))
    upper = float(np.percentile(values, 98))

    if upper <= lower:
        upper = float(values.max())
        lower = float(values.min())

    span = max(upper - lower, 1.0)
    normalized = np.clip((confidence_grid.astype(np.float32) - lower) / span, 0, 1)
    normalized = np.power(normalized, 0.75)
    normalized_safe = np.nan_to_num(normalized, nan=0.0, posinf=1.0, neginf=0.0)

    palette = np.array([
        [254, 229, 217],
        [252, 174, 145],
        [251, 106, 74],
        [222, 45, 38],
        [165, 15, 21]
    ], dtype=np.float32)
    scaled = normalized_safe * (len(palette) - 1)
    low_index = np.floor(scaled).astype(np.int32)
    high_index = np.clip(low_index + 1, 0, len(palette) - 1)
    blend = (scaled - low_index)[..., None]
    colors = palette[low_index] * (1 - blend) + palette[high_index] * blend

    rgba[..., :3] = np.where(valid_mask[..., None], colors.astype(np.uint8), 0)
    rgba[..., 3] = np.where(valid_mask, np.clip(110 + normalized_safe * 145, 0, 255), 0).astype(np.uint8)
    return rgba


def colorize_temperature(temperature_grid: np.ndarray):
    rgba = np.zeros((temperature_grid.shape[0], temperature_grid.shape[1], 4), dtype=np.uint8)
    valid_mask = np.isfinite(temperature_grid)

    if not np.any(valid_mask):
        return rgba

    values = temperature_grid[valid_mask].astype(np.float32)
    lower = float(np.percentile(values, 2))
    upper = float(np.percentile(values, 98))

    if upper <= lower:
        lower = float(values.min())
        upper = float(values.max())

    span = max(upper - lower, 1.0)
    normalized = np.clip((temperature_grid.astype(np.float32) - lower) / span, 0, 1)
    normalized_safe = np.nan_to_num(normalized, nan=0.0, posinf=1.0, neginf=0.0)

    palette = np.array([
        [49, 54, 149],
        [69, 117, 180],
        [116, 173, 209],
        [254, 224, 144],
        [244, 109, 67],
        [165, 0, 38]
    ], dtype=np.float32)
    scaled = normalized_safe * (len(palette) - 1)
    low_index = np.floor(scaled).astype(np.int32)
    high_index = np.clip(low_index + 1, 0, len(palette) - 1)
    blend = (scaled - low_index)[..., None]
    colors = palette[low_index] * (1 - blend) + palette[high_index] * blend

    rgba[..., :3] = np.where(valid_mask[..., None], colors.astype(np.uint8), 0)
    rgba[..., 3] = np.where(valid_mask, 170, 0).astype(np.uint8)
    return rgba


def colorize_aod(aod_grid: np.ndarray):
    rgba = np.zeros((aod_grid.shape[0], aod_grid.shape[1], 4), dtype=np.uint8)
    valid_mask = np.isfinite(aod_grid)

    if not np.any(valid_mask):
        return rgba

    values = aod_grid[valid_mask].astype(np.float32)
    lower = float(np.percentile(values, 2))
    upper = float(np.percentile(values, 98))

    if upper <= lower:
        lower = float(values.min())
        upper = float(values.max())

    span = max(upper - lower, 1e-6)
    normalized = np.clip((aod_grid.astype(np.float32) - lower) / span, 0, 1)
    normalized_safe = np.nan_to_num(normalized, nan=0.0, posinf=1.0, neginf=0.0)

    palette = np.array([
        [49, 130, 189],
        [65, 182, 196],
        [127, 205, 187],
        [255, 255, 179],
        [253, 174, 97],
        [215, 25, 28]
    ], dtype=np.float32)
    scaled = normalized_safe * (len(palette) - 1)
    low_index = np.floor(scaled).astype(np.int32)
    high_index = np.clip(low_index + 1, 0, len(palette) - 1)
    blend = (scaled - low_index)[..., None]
    colors = palette[low_index] * (1 - blend) + palette[high_index] * blend

    rgba[..., :3] = np.where(valid_mask[..., None], colors.astype(np.uint8), 0)
    rgba[..., 3] = np.where(valid_mask, 160, 0).astype(np.uint8)
    return rgba


def colorize_scalar_grid(value_grid: np.ndarray, palette: list[list[int]]):
    rgba = np.zeros((value_grid.shape[0], value_grid.shape[1], 4), dtype=np.uint8)
    valid_mask = np.isfinite(value_grid)

    if not np.any(valid_mask):
        return rgba

    values = value_grid[valid_mask].astype(np.float32)
    lower = float(np.percentile(values, 5))
    upper = float(np.percentile(values, 95))

    if upper <= lower:
        lower = float(values.min())
        upper = float(values.max())

    span = max(upper - lower, 1e-6)
    normalized = np.clip((value_grid.astype(np.float32) - lower) / span, 0, 1)
    normalized_safe = np.nan_to_num(normalized, nan=0.0, posinf=1.0, neginf=0.0)

    def parse_color(color_value):
        if isinstance(color_value, str):
            normalized = color_value.lstrip("#")
            return [
                int(normalized[0:2], 16),
                int(normalized[2:4], 16),
                int(normalized[4:6], 16),
            ]
        return color_value

    palette_array = np.array([parse_color(color) for color in palette], dtype=np.float32)
    scaled = normalized_safe * (len(palette_array) - 1)
    low_index = np.floor(scaled).astype(np.int32)
    high_index = np.clip(low_index + 1, 0, len(palette_array) - 1)
    blend = (scaled - low_index)[..., None]
    colors = palette_array[low_index] * (1 - blend) + palette_array[high_index] * blend

    rgba[..., :3] = np.where(valid_mask[..., None], colors.astype(np.uint8), 0)
    rgba[..., 3] = np.where(valid_mask, 172, 0).astype(np.uint8)
    return rgba


def get_leaflet_bounds(src):
    if src.crs is None or getattr(src.crs, "is_geographic", False):
        minx, miny, maxx, maxy = src.bounds
        return [[miny, minx], [maxy, maxx]]

    minx, miny, maxx, maxy = transform_bounds(
        src.crs,
        "EPSG:4326",
        *src.bounds,
        densify_pts=21
    )
    return [[miny, minx], [maxy, maxx]]


def build_overlay_bounds(transform, height: int, width: int):
    require_geospatial_runtime()
    left, bottom, right, top = array_bounds(height, width, transform)
    return [[bottom, left], [top, right]]


def get_catchment_shape(catchment_id: str):
    require_geospatial_runtime()
    catchment_geometry = load_catchment_geometries().get(str(catchment_id))
    return shape(catchment_geometry) if catchment_geometry else None


def normalize_lake_id(value):
    if value is None or pd.isna(value):
        return None

    try:
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
    except (TypeError, ValueError):
        pass

    return str(value)


def get_lake_record(lake_id: str):
    require_geospatial_runtime()
    lakes_gdf = load_lakes_with_catchments()
    if lakes_gdf.empty:
        return None

    normalized_id = normalize_lake_id(lake_id)
    matches = lakes_gdf[lakes_gdf["Lake_ID"].apply(normalize_lake_id) == normalized_id]
    if matches.empty:
        return None

    return matches.iloc[0]


def get_lake_shape(lake_id: str):
    require_geospatial_runtime()
    lake_record = get_lake_record(lake_id)
    if lake_record is None:
        return None

    geometry = lake_record.geometry
    if geometry is None or geometry.is_empty:
        return None

    return geometry


def resolve_catchment_id_for_lake_geometry(lake_geometry):
    require_geospatial_runtime()
    catchments_gdf = load_catchments_gdf()
    if lake_geometry is None or catchments_gdf.empty:
        return None

    representative_point = lake_geometry.representative_point()
    containing_matches = catchments_gdf[catchments_gdf.geometry.contains(representative_point)]
    if not containing_matches.empty:
        return str(containing_matches.iloc[0]["catchment_id"])

    intersecting_matches = catchments_gdf[catchments_gdf.geometry.intersects(lake_geometry)]
    if not intersecting_matches.empty:
        intersecting_matches = intersecting_matches.assign(
            intersection_area=intersecting_matches.geometry.intersection(lake_geometry).area
        )
        best_match = intersecting_matches.sort_values("intersection_area", ascending=False).iloc[0]
        return str(best_match["catchment_id"])

    return None


def get_catchment_id_for_lake(lake_id: str):
    require_geospatial_runtime()
    lake_record = get_lake_record(lake_id)
    if lake_record is None:
        return None

    catchment_id = lake_record.get("catchment_id")
    if catchment_id is not None and not pd.isna(catchment_id):
        return str(catchment_id)

    return resolve_catchment_id_for_lake_geometry(lake_record.geometry)


def get_metric_crs():
    return "EPSG:3857"


def get_burned_area_legend():
    return {
        "title": "Burned Area Intensity",
        "min_label": "Low",
        "max_label": "High",
        "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"],
        "position": "bottomright"
    }


def get_temperature_legend():
    return {
        "title": "Temperature (°C)",
        "min_label": "Cold",
        "max_label": "Hot",
        "colors": ["#313695", "#4575b4", "#74add1", "#fee090", "#f46d43", "#a50026"],
        "position": "bottomleft"
    }


def get_aod_legend():
    return {
        "title": "AOD Concentration",
        "min_label": "Low",
        "max_label": "High",
        "colors": ["#3182bd", "#41b6c4", "#7fcdbb", "#ffffb3", "#fdae61", "#d7191c"],
        "position": "bottomleft"
    }


def get_lake_cci_legend(variable_name: str):
    if variable_name == "chla":
        return {
            "title": "CHLA Layer",
            "unit": "mg/m3",
            "min_label": "Low",
            "max_label": "High",
            "colors": ["#2563eb", "#22c55e", "#fde047", "#ef4444"],
            "position": "bottomright"
        }

    if variable_name == "lake_surface_water_temperature":
        return {
            "title": "LSWT Layer",
            "unit": "°C",
            "min_label": "Cold",
            "max_label": "Warm",
            "colors": ["#2563eb", "#22d3ee", "#fde047", "#f97316", "#dc2626"],
            "position": "bottomright"
        }

    if variable_name == "tsm":
        return {
            "title": "Turbidity Layer",
            "unit": "g/m3",
            "min_label": "Clear",
            "max_label": "Turbid",
            "colors": ["#dbeafe", "#d6c6a5", "#8b5a2b"],
            "position": "bottomright"
        }

    return None


def get_month_key(date_value) -> str | None:
    if date_value is None:
        return None

    try:
        return pd.to_datetime(date_value).to_period("M").strftime("%Y-%m")
    except (TypeError, ValueError):
        return None


def build_month_candidates(start_date: str, end_date: str):
    start_month = get_month_key(start_date)
    end_month = get_month_key(end_date)

    if not start_month:
        return []

    start_timestamp = pd.to_datetime(start_month)
    end_timestamp = pd.to_datetime(end_month) if end_month else start_timestamp
    month_range = pd.date_range(start=start_timestamp, end=end_timestamp, freq="MS")
    candidates = [month.strftime("%Y-%m") for month in month_range]

    if start_month not in candidates:
        candidates.insert(0, start_month)

    return candidates


def absolutize_overlay_payload(payload):
    if not payload:
        return None

    normalized = dict(payload)
    image_url = normalized.get("image_url")
    if image_url and image_url.startswith("/"):
        normalized["image_url"] = request.host_url.rstrip("/") + image_url
    return normalized


def resolve_overlay_from_demo_manifest(section_name: str, variable_name: str, entity_id: str | None, start_date: str, end_date: str):
    if not entity_id:
        return None

    manifest = load_demo_overlay_index()
    section = manifest.get(section_name, {})
    variable_entries = section.get(variable_name, {})
    month_entries = variable_entries.get(str(entity_id))

    if not month_entries:
        return None

    month_candidates = build_month_candidates(start_date, end_date)
    for month_key in month_candidates:
        if month_key in month_entries:
            return absolutize_overlay_payload(month_entries[month_key])

    available_months = sorted(month_entries.keys())
    if not available_months:
        return None

    target_month = month_candidates[0] if month_candidates else available_months[0]
    target_timestamp = pd.to_datetime(target_month)
    fallback_month = min(
        available_months,
        key=lambda month_key: abs((pd.to_datetime(month_key) - target_timestamp).days)
    )
    return absolutize_overlay_payload(month_entries[fallback_month])


def get_burned_overlay_paths(catchment_id: str, start_date: str, end_date: str):
    overlay_name = (
        f"burned_area_{catchment_id}_{pd.to_datetime(start_date):%Y%m%d}_{pd.to_datetime(end_date):%Y%m%d}.png"
    )
    overlay_path = OVERLAY_DIR / overlay_name
    metadata_path = overlay_path.with_suffix(".json")
    return overlay_name, overlay_path, metadata_path


def build_burned_raster_bundle(catchment_id: str, start_date: str, end_date: str):
    monthly_rasters = [
        (month_start, raster_path)
        for month_start in month_start_range(start_date, end_date)
        for raster_path in [get_firecci_confidence_path(month_start)]
        if raster_path is not None
    ]

    if not monthly_rasters:
        app.logger.warning(
            "No burned raster files found for catchment=%s range=%s..%s",
            catchment_id,
            start_date,
            end_date
        )
        return None

    catchment_shape = get_catchment_shape(catchment_id)
    if catchment_shape is None:
        return None

    aggregate = None
    bounds = None
    monthly_burned_area = {}
    monthly_pixel_stats = {}
    raster_count = 0
    raster_tiles_used = []

    for month_start, raster_path in monthly_rasters:
        month_key = month_start.strftime("%Y-%m")

        try:
            with rasterio.open(raster_path) as src:
                raster_count += 1
                raster_tiles_used.append(raster_path.name)
                print(f"[burned_overlay] raster loaded successfully: {raster_path}")
                clipped_data, valid_mask, clipped_transform = clip_burned_raster(src, catchment_shape)
                debug_stats = summarize_clipped_burned_data(clipped_data, valid_mask)
                pixel_count = int(clipped_data.size)
                burned_area_ha, burned_pixel_count, valid_pixel_count = compute_burned_area_hectares(
                    clipped_data,
                    valid_mask,
                    clipped_transform,
                    src.crs
                )
                forced_burned_pixel_count = int(np.count_nonzero(valid_mask & (clipped_data > 0)))
        except Exception as error:
            app.logger.warning(
                "Burned raster processing failed for catchment=%s month=%s file=%s: %s",
                catchment_id,
                month_key,
                raster_path,
                error
            )
            monthly_burned_area[month_key] = 0.0
            monthly_pixel_stats[month_key] = {
                "pixel_count": 0,
                "valid_pixel_count": 0,
                "burned_pixel_count": 0
            }
            continue

        monthly_burned_area[month_key] = round(burned_area_ha, 2)
        monthly_pixel_stats[month_key] = {
            "pixel_count": pixel_count,
            "valid_pixel_count": valid_pixel_count,
            "burned_pixel_count": burned_pixel_count
        }
        print(
            f"[burned_overlay] catchment={catchment_id} month={month_key} "
            f"raster_used={raster_path.name} "
            f"clipped_shape={clipped_data.shape} "
            f"total_pixels={debug_stats['total_pixels']} "
            f"valid_pixels={debug_stats['valid_pixels']} "
            f"min={debug_stats['min'] if debug_stats['min'] is not None else 'nan'} "
            f"max={debug_stats['max'] if debug_stats['max'] is not None else 'nan'} "
            f"mean={debug_stats['mean'] if debug_stats['mean'] is not None else 'nan'} "
            f"unique_sample={debug_stats['unique_sample']} "
            f"pixels_gt_0={debug_stats['count_gt_0']} "
            f"pixels_gt_10={debug_stats['count_gt_10']} "
            f"pixels_gt_20={debug_stats['count_gt_20']} "
            f"threshold={BURNED_PIXEL_THRESHOLD} "
            f"burned_pixels={burned_pixel_count} "
            f"forced_gt_0_burned_pixels={forced_burned_pixel_count} "
            f"burned_area_ha={monthly_burned_area[month_key]}"
        )

        if valid_pixel_count == 0:
            continue

        if aggregate is None:
            aggregate = clipped_data if aggregate is None else np.fmax(aggregate, clipped_data)
            if bounds is None:
                bounds = build_overlay_bounds(
                    clipped_transform,
                    clipped_data.shape[0],
                    clipped_data.shape[1]
                )
            continue

        aggregate = np.fmax(aggregate, clipped_data)

    if aggregate is None or bounds is None:
        app.logger.warning(
            "Burned raster clipping returned no valid pixels for catchment=%s range=%s..%s",
            catchment_id,
            start_date,
            end_date
        )
        return {
            "bounds": None,
            "aggregate": None,
            "monthly_burned_area": monthly_burned_area,
            "monthly_pixel_stats": monthly_pixel_stats,
            "has_burned_data": False,
            "raster_count": raster_count,
            "raster_tiles_used": raster_tiles_used
        }

    has_burned_data = bool(np.any(np.isfinite(aggregate) & (aggregate > BURNED_PIXEL_THRESHOLD)))

    return {
        "bounds": bounds,
        "aggregate": aggregate,
        "monthly_burned_area": monthly_burned_area,
        "monthly_pixel_stats": monthly_pixel_stats,
        "has_burned_data": has_burned_data,
        "raster_count": raster_count,
        "raster_tiles_used": raster_tiles_used
    }


def build_burned_area_overlay(catchment_id: str, start_date: str, end_date: str, raster_bundle=None):
    require_geospatial_runtime()
    raster_paths = [
        get_firecci_confidence_path(month)
        for month in month_start_range(start_date, end_date)
    ]
    raster_paths = [p for p in raster_paths if p is not None]

    if not raster_paths:
        print(f"[burned_overlay] No rasters found for {start_date} → {end_date}")
        return None

    catchment_geometry = load_catchment_geometries().get(str(catchment_id))
    if not catchment_geometry:
        print(f"[burned_overlay] No geometry for catchment {catchment_id}")
        return None

    aggregate = None
    bounds = None

    for raster_path in raster_paths:
        try:
            with rasterio.open(raster_path) as src:
                clipped, transform = mask(
                    src,
                    [catchment_geometry],
                    crop=True,
                    filled=False
                )

                data = np.asarray(clipped[0], dtype=np.float32)
                data[np.ma.getmaskarray(clipped[0])] = np.nan

                if np.all(np.isnan(data)):
                    continue

                aggregate = data if aggregate is None else np.fmax(aggregate, data)

                if bounds is None:
                    bounds = build_overlay_bounds(
                        transform,
                        data.shape[0],
                        data.shape[1]
                    )

        except Exception as e:
            print(f"[burned_overlay] ERROR reading {raster_path}: {e}")
            continue

    if aggregate is None or bounds is None:
        print(f"[burned_overlay] No valid burned data after clipping")
        return None

    rgba = colorize_burned_area(aggregate)

    if not np.any(rgba[..., 3] > 0):
        print(f"[burned_overlay] Image fully transparent → no burned pixels visible")
        return None

    overlay_name = f"burned_{catchment_id}.png"
    overlay_path = OVERLAY_DIR / overlay_name

    image = Image.fromarray(rgba, mode="RGBA")

    if max(image.size) > MAX_OVERLAY_DIMENSION:
        scale = MAX_OVERLAY_DIMENSION / float(max(image.size))
        image = image.resize(
            (
                int(image.size[0] * scale),
                int(image.size[1] * scale)
            ),
            Image.Resampling.LANCZOS
        )

    image.save(overlay_path, optimize=True)

    print(f"[burned_overlay] created -> {overlay_path}")

    return {
        "image_url": request.host_url.rstrip("/") + url_for("serve_overlay", filename=overlay_name),
        "bounds": bounds,
        "opacity": 0.8,
        "legend": get_burned_area_legend(),
        "has_burned_data": True
    }


def clip_scalar_raster(src, catchment_shape):
    require_geospatial_runtime()
    clipped, clipped_transform = mask(
        src,
        [get_catchment_geometry_for_raster(src, catchment_shape)],
        crop=True,
        filled=False
    )

    clipped_band = clipped[0]
    clipped_data = np.asarray(clipped_band, dtype=np.float32)
    valid_mask = ~np.ma.getmaskarray(clipped_band)
    valid_mask &= np.isfinite(clipped_data)

    if src.nodata is not None:
        valid_mask &= clipped_data != src.nodata

    clipped_data[~valid_mask] = np.nan
    return clipped_data, valid_mask, clipped_transform


def normalize_lake_cci_values(variable_name: str, clipped_data: np.ndarray):
    normalized = clipped_data.astype(np.float32).copy()
    if variable_name == "lake_surface_water_temperature":
        normalized = normalized - 273.15
    return normalized


def get_analysis_target_mean(analysis_records: pd.DataFrame, variable_name: str):
    if analysis_records is None or analysis_records.empty or variable_name not in analysis_records.columns:
        return None

    values = pd.to_numeric(analysis_records[variable_name], errors="coerce").dropna()
    if values.empty:
        return None

    return float(values.mean())


def build_lake_cci_overlay(
    lake_id: str,
    variable_name: str,
    start_date: str,
    end_date: str,
    analysis_records: pd.DataFrame | None = None
):
    require_geospatial_runtime()
    legend = get_lake_cci_legend(variable_name)
    if not lake_id or legend is None:
        return None

    lake_shape = get_lake_shape(lake_id)
    if lake_shape is None:
        return None

    day_range = pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date), freq="D")
    raster_paths = [get_lake_cci_netcdf_path(day_timestamp) for day_timestamp in day_range]
    raster_paths = [path for path in raster_paths if path is not None]

    if not raster_paths:
        return None

    aggregate_layers = []
    bounds = None

    for raster_path in raster_paths:
        subdataset_path = f"netcdf:{raster_path}:{variable_name}"
        try:
            with rasterio.open(subdataset_path) as src:
                clipped_data, valid_mask, clipped_transform = clip_scalar_raster(src, lake_shape)

                if not np.any(valid_mask):
                    continue

                normalized_values = normalize_lake_cci_values(variable_name, clipped_data)
                aggregate_layers.append(normalized_values)

                if bounds is None:
                    bounds = build_overlay_bounds(
                        clipped_transform,
                        normalized_values.shape[0],
                        normalized_values.shape[1]
                    )
        except Exception as error:
            app.logger.warning(
                "LakeCCI overlay build failed for lake=%s variable=%s file=%s: %s",
                lake_id,
                variable_name,
                raster_path,
                error
            )

    if not aggregate_layers or bounds is None:
        return None

    stacked_layers = np.stack(aggregate_layers, axis=0)
    valid_counts = np.sum(np.isfinite(stacked_layers), axis=0)
    aggregate = np.divide(
        np.nansum(stacked_layers, axis=0),
        valid_counts,
        out=np.full(stacked_layers.shape[1:], np.nan, dtype=np.float32),
        where=valid_counts > 0
    )

    target_mean = get_analysis_target_mean(analysis_records, variable_name)
    current_mean = float(np.nanmean(aggregate)) if np.any(np.isfinite(aggregate)) else None
    if (
        target_mean is not None
        and current_mean is not None
        and np.isfinite(current_mean)
        and abs(current_mean) > 1e-9
    ):
        scale_factor = target_mean / current_mean
        aggregate = aggregate * scale_factor
        if variable_name in {"chla", "tsm"}:
            aggregate = np.where(np.isfinite(aggregate), np.maximum(aggregate, 0.0), np.nan)

    rgba = colorize_scalar_grid(aggregate, legend["colors"])

    if not np.any(rgba[..., 3] > 0):
        return None

    overlay_name = (
        f"{variable_name}_{lake_id}_{pd.to_datetime(start_date):%Y%m%d}_{pd.to_datetime(end_date):%Y%m%d}.png"
    )
    overlay_path = LAKE_CCI_OVERLAY_DIR / overlay_name
    image = Image.fromarray(rgba, mode="RGBA")

    if max(image.size) > MAX_OVERLAY_DIMENSION:
        scale = MAX_OVERLAY_DIMENSION / float(max(image.size))
        image = image.resize(
            (
                int(image.size[0] * scale),
                int(image.size[1] * scale)
            ),
            Image.Resampling.LANCZOS
        )

    image.save(overlay_path, optimize=True)

    return {
        "image_url": request.host_url.rstrip("/") + url_for("serve_overlay", filename=overlay_name),
        "bounds": bounds,
        "opacity": 0.82,
        "legend": legend,
        "has_data": True
    }


def build_temperature_overlay(catchment_id: str, start_date: str, end_date: str):
    require_geospatial_runtime()
    raster_paths = [
        get_temperature_raster_path(month)
        for month in month_start_range(start_date, end_date)
    ]
    raster_paths = [path for path in raster_paths if path is not None]

    if not raster_paths:
        return None

    catchment_shape = get_catchment_shape(catchment_id)
    if catchment_shape is None:
        return None

    aggregate_layers = []
    bounds = None

    for raster_path in raster_paths:
        try:
            with rasterio.open(raster_path) as src:
                clipped_data, valid_mask, clipped_transform = clip_scalar_raster(src, catchment_shape)

                if not np.any(valid_mask):
                    continue

                aggregate_layers.append(clipped_data)

                if bounds is None:
                    bounds = build_overlay_bounds(
                        clipped_transform,
                        clipped_data.shape[0],
                        clipped_data.shape[1]
                    )
        except Exception as error:
            app.logger.warning(
                "Temperature overlay build failed for catchment=%s file=%s: %s",
                catchment_id,
                raster_path,
                error
            )

    if not aggregate_layers or bounds is None:
        return None

    # Keep the overlay lightweight by aggregating only the requested monthly stack.
    stacked_layers = np.stack(aggregate_layers, axis=0)
    valid_counts = np.sum(np.isfinite(stacked_layers), axis=0)
    aggregate = np.divide(
        np.nansum(stacked_layers, axis=0),
        valid_counts,
        out=np.full(stacked_layers.shape[1:], np.nan, dtype=np.float32),
        where=valid_counts > 0
    )
    rgba = colorize_temperature(aggregate)

    if not np.any(rgba[..., 3] > 0):
        return None

    overlay_name = (
        f"temperature_{catchment_id}_{pd.to_datetime(start_date):%Y%m%d}_{pd.to_datetime(end_date):%Y%m%d}.png"
    )
    overlay_path = OVERLAY_DIR / overlay_name
    image = Image.fromarray(rgba, mode="RGBA")

    if max(image.size) > MAX_OVERLAY_DIMENSION:
        scale = MAX_OVERLAY_DIMENSION / float(max(image.size))
        image = image.resize(
            (
                int(image.size[0] * scale),
                int(image.size[1] * scale)
            ),
            Image.Resampling.LANCZOS
        )

    image.save(overlay_path, optimize=True)

    return {
        "image_url": request.host_url.rstrip("/") + url_for("serve_overlay", filename=overlay_name),
        "bounds": bounds,
        "opacity": 0.66,
        "legend": get_temperature_legend(),
        "has_temperature_data": True
    }


def build_aod_overlay(catchment_id: str, start_date: str, end_date: str):
    require_geospatial_runtime()
    raster_paths = [
        get_aod_raster_path(month)
        for month in month_start_range(start_date, end_date)
    ]
    raster_paths = [path for path in raster_paths if path is not None]

    if not raster_paths:
        return None

    catchment_shape = get_catchment_shape(catchment_id)
    if catchment_shape is None:
        return None

    aggregate_layers = []
    bounds = None

    for raster_path in raster_paths:
        try:
            with rasterio.open(raster_path) as src:
                clipped_data, valid_mask, clipped_transform = clip_scalar_raster(src, catchment_shape)

                if not np.any(valid_mask):
                    continue

                aggregate_layers.append(clipped_data)

                if bounds is None:
                    bounds = build_overlay_bounds(
                        clipped_transform,
                        clipped_data.shape[0],
                        clipped_data.shape[1]
                    )
        except Exception as error:
            app.logger.warning(
                "AOD overlay build failed for catchment=%s file=%s: %s",
                catchment_id,
                raster_path,
                error
            )

    if not aggregate_layers or bounds is None:
        return None

    stacked_layers = np.stack(aggregate_layers, axis=0)
    valid_counts = np.sum(np.isfinite(stacked_layers), axis=0)
    aggregate = np.divide(
        np.nansum(stacked_layers, axis=0),
        valid_counts,
        out=np.full(stacked_layers.shape[1:], np.nan, dtype=np.float32),
        where=valid_counts > 0
    )
    rgba = colorize_aod(aggregate)

    if not np.any(rgba[..., 3] > 0):
        return None

    overlay_name = (
        f"aod_{catchment_id}_{pd.to_datetime(start_date):%Y%m%d}_{pd.to_datetime(end_date):%Y%m%d}.png"
    )
    overlay_path = AOD_OVERLAY_DIR / overlay_name
    image = Image.fromarray(rgba, mode="RGBA")

    if max(image.size) > MAX_OVERLAY_DIMENSION:
        scale = MAX_OVERLAY_DIMENSION / float(max(image.size))
        image = image.resize(
            (
                int(image.size[0] * scale),
                int(image.size[1] * scale)
            ),
            Image.Resampling.LANCZOS
        )

    image.save(overlay_path, optimize=True)

    return {
        "image_url": request.host_url.rstrip("/") + url_for("serve_overlay", filename=overlay_name),
        "bounds": bounds,
        "opacity": 0.62,
        "legend": get_aod_legend(),
        "has_aod_data": True
    }


def build_safe_analysis_record(catchment_id: str, start_date: str):
    fallback_month = None

    if start_date:
        try:
            fallback_month = pd.to_datetime(start_date).to_period("M").to_timestamp()
        except (TypeError, ValueError):
            fallback_month = None

    return {
        "catchment_id": str(catchment_id) if catchment_id else "",
        "date": fallback_month,
        "burned_area": 0.0,
        "rainfall": 0.0,
        "temperature": None,
        "aod": None,
        "chla": None,
        "lake_surface_water_temperature": None,
        "tsm": None,
        "land_cover": None
    }


def build_safe_analysis_response(
    catchment_id: str,
    start_date: str,
    end_date: str | None,
    warning: str,
    summary=None,
    selected_variables=None,
    aggregation: str = "monthly"
):
    safe_records = pd.DataFrame([build_safe_analysis_record(catchment_id, start_date)])
    safe_start = pd.to_datetime(start_date) if start_date else None
    safe_end = pd.to_datetime(end_date) if end_date else safe_start
    safe_records = resample_analysis_records(safe_records, aggregation, safe_start, safe_end)
    return {
        "records": serialize_records(safe_records, aggregation),
        "overlay": None,
        "temperature_overlay": None,
        "aod_overlay": None,
        "chla_overlay": None,
        "lswt_overlay": None,
        "tsm_overlay": None,
        "selected_variables": selected_variables if selected_variables is not None else DEFAULT_RESULT_VARIABLES.copy(),
        "aggregation": normalize_aggregation_mode(aggregation),
        "summary": summary if summary is not None else {
            "lake_coverage_percent": 0.0,
            "water_insight": "Analysis unavailable"
        },
        "warning": warning
    }


def get_catchment_geometry_for_raster(src, catchment_shape):
    require_geospatial_runtime()
    geometry = catchment_shape.__geo_interface__

    if src.crs is None:
        return geometry

    if getattr(src.crs, "is_geographic", False) or str(src.crs).upper() == "EPSG:4326":
        return geometry

    return transform_geom("EPSG:4326", src.crs, geometry)


def raster_intersects_catchment(src, catchment_shape):
    require_geospatial_runtime()
    if src.crs is None:
        catchment_geometry = catchment_shape
    else:
        catchment_geometry = shape(get_catchment_geometry_for_raster(src, catchment_shape))

    return box(*src.bounds).intersects(catchment_geometry)


def clip_burned_raster(src, catchment_shape):
    require_geospatial_runtime()
    clipped, clipped_transform = mask(
        src,
        [get_catchment_geometry_for_raster(src, catchment_shape)],
        crop=True,
        filled=False
    )

    clipped_band = clipped[0]
    clipped_data = np.asarray(clipped_band, dtype=np.float32)
    valid_mask = ~np.ma.getmaskarray(clipped_band)

    if src.nodata is not None:
        valid_mask &= clipped_data != src.nodata

    valid_mask &= np.isfinite(clipped_data)
    clipped_data[~valid_mask] = np.nan
    return clipped_data, valid_mask, clipped_transform


def summarize_clipped_burned_data(clipped_data: np.ndarray, valid_mask: np.ndarray):
    total_pixels = int(clipped_data.size)
    valid_pixel_count = int(np.count_nonzero(valid_mask))

    if valid_pixel_count == 0:
        return {
            "total_pixels": total_pixels,
            "valid_pixels": 0,
            "min": None,
            "max": None,
            "mean": None,
            "unique_sample": [],
            "count_gt_0": 0,
            "count_gt_10": 0,
            "count_gt_20": 0,
        }

    valid_values = clipped_data[valid_mask]
    unique_sample = np.unique(valid_values)[:20]

    return {
        "total_pixels": total_pixels,
        "valid_pixels": valid_pixel_count,
        "min": float(np.nanmin(valid_values)),
        "max": float(np.nanmax(valid_values)),
        "mean": float(np.nanmean(valid_values)),
        "unique_sample": unique_sample.tolist(),
        "count_gt_0": int(np.count_nonzero(valid_values > 0)),
        "count_gt_10": int(np.count_nonzero(valid_values > 10)),
        "count_gt_20": int(np.count_nonzero(valid_values > 20)),
    }


def get_pixel_area_by_row_hectares(transform_matrix, row_index: int, source_crs):
    pixel_width = abs(float(transform_matrix.a))
    pixel_height = abs(float(transform_matrix.e))

    if source_crs is not None and not getattr(source_crs, "is_geographic", False):
        return (pixel_width * pixel_height) / 10000.0

    left = float(transform_matrix.c)
    top = float(transform_matrix.f + (row_index * transform_matrix.e))
    bottom = float(top + transform_matrix.e)
    right = float(left + transform_matrix.a)

    xs, ys = transform(
        source_crs or "EPSG:4326",
        get_metric_crs(),
        [left, right, left],
        [top, top, bottom]
    )
    width_m = abs(xs[1] - xs[0])
    height_m = abs(ys[0] - ys[2])
    return (width_m * height_m) / 10000.0


def compute_burned_area_hectares(clipped_data: np.ndarray, valid_mask: np.ndarray, clipped_transform, source_crs):
    burned_mask = valid_mask & (clipped_data >= BURNED_PIXEL_THRESHOLD)
    burned_pixel_count = int(np.count_nonzero(burned_mask))
    valid_pixel_count = int(np.count_nonzero(valid_mask))

    if burned_pixel_count == 0:
        return 0.0, burned_pixel_count, valid_pixel_count

    burned_rows, burned_counts = np.unique(np.where(burned_mask)[0], return_counts=True)
    area_hectares = 0.0

    for row_index, row_count in zip(burned_rows.tolist(), burned_counts.tolist()):
        area_hectares += row_count * get_pixel_area_by_row_hectares(
            clipped_transform,
            row_index,
            source_crs
        )

    return float(area_hectares), burned_pixel_count, valid_pixel_count


def build_monthly_burned_area_lookup(catchment_id: str, start_date: str, end_date: str):
    raster_bundle = build_burned_raster_bundle(catchment_id, start_date, end_date)
    if not raster_bundle:
        return {}

    return raster_bundle.get("monthly_burned_area", {})


def build_analysis_records(dataset: pd.DataFrame, catchment_id: str, start_timestamp, end_timestamp):
    month_start = pd.to_datetime(start_timestamp).to_period("M").to_timestamp()
    month_end = pd.to_datetime(end_timestamp).to_period("M").to_timestamp()
    monthly_index = pd.DataFrame({
        "date": month_start_range(month_start, month_end)
    })

    subset = dataset[
        (dataset["catchment_id"] == catchment_id)
        & (dataset["date"] >= month_start)
        & (dataset["date"] <= month_end)
    ].copy()
    print(f"[analysis] catchment_id={catchment_id} dataset_rows_found={len(subset)}")
    print(f"[analysis] catchment_id={catchment_id} dataset_burned_area_values={subset['burned_area'].tolist() if 'burned_area' in subset.columns else []}")

    dataset_columns = [
        column
        for column in [
            "catchment_id",
            "date",
            "burned_area",
            "rainfall",
            "temperature",
            "aod",
            "chla",
            "lake_surface_water_temperature",
            "tsm",
            "land_cover",
        ]
        if column in subset.columns
    ]
    subset = subset[dataset_columns]

    if subset.empty:
        records = monthly_index.copy()
    else:
        records = monthly_index.merge(subset, on="date", how="left")

    if "catchment_id" not in records.columns:
        records["catchment_id"] = str(catchment_id)
    else:
        records["catchment_id"] = records["catchment_id"].fillna(str(catchment_id))
    if "rainfall" not in records.columns:
        records["rainfall"] = 0.0
    else:
        records["rainfall"] = pd.to_numeric(records["rainfall"], errors="coerce").fillna(0.0)

    if "burned_area" not in records.columns:
        records["burned_area"] = 0.0
    else:
        records["burned_area"] = pd.to_numeric(records["burned_area"], errors="coerce").fillna(0.0)

    if "temperature" not in records.columns:
        records["temperature"] = pd.NA
    else:
        records["temperature"] = pd.to_numeric(records["temperature"], errors="coerce")

    if "aod" not in records.columns:
        records["aod"] = pd.NA
    else:
        records["aod"] = pd.to_numeric(records["aod"], errors="coerce")

    if "chla" not in records.columns:
        records["chla"] = pd.NA
    else:
        records["chla"] = pd.to_numeric(records["chla"], errors="coerce")

    if "lake_surface_water_temperature" not in records.columns:
        records["lake_surface_water_temperature"] = pd.NA
    else:
        records["lake_surface_water_temperature"] = pd.to_numeric(
            records["lake_surface_water_temperature"],
            errors="coerce"
        )

    if "tsm" not in records.columns:
        records["tsm"] = pd.NA
    else:
        records["tsm"] = pd.to_numeric(records["tsm"], errors="coerce")

    if "land_cover" not in records.columns:
        records["land_cover"] = pd.NA

    preferred_columns = [
        "catchment_id",
        "date",
        "burned_area",
        "rainfall",
        "temperature",
        "aod",
        "chla",
        "lake_surface_water_temperature",
        "tsm",
        "land_cover",
    ]
    return records[preferred_columns]


def build_lakes_overview_geojson():
    demo_overview = load_demo_lakes_overview()
    if demo_overview.get("features"):
        return demo_overview

    lakes_gdf = load_lakes_with_catchments()
    if lakes_gdf.empty:
        return {"type": "FeatureCollection", "features": []}

    overview = lakes_gdf[["Lake_ID", "catchment_id", "geometry"]].copy()
    overview["geometry"] = overview.geometry.simplify(0.002, preserve_topology=True)
    overview = overview[overview.geometry.notna() & ~overview.geometry.is_empty]
    return json.loads(overview.to_json())


def build_lake_selection_payload(lake_id: str):
    demo_entry = load_demo_lake_selection_index().get(normalize_lake_id(lake_id))
    if demo_entry is not None:
        normalized_lake_id = normalize_lake_id(demo_entry.get("lake_id"))
        lake_feature = get_demo_lake_feature(normalized_lake_id)
        catchment_id = demo_entry.get("catchment_id")
        return {
            "lake_id": normalized_lake_id,
            "catchment_id": catchment_id,
            "lake_label": demo_entry.get("lake_label") or f"Lake {normalized_lake_id}",
            "lake": {
                "type": "Feature",
                "properties": {"lake_id": normalized_lake_id},
                "geometry": (lake_feature or {}).get("geometry")
            } if lake_feature else None,
            "catchment": get_demo_catchment_feature(catchment_id)
        }

    catchment_id = get_catchment_id_for_lake(lake_id)
    lake_record = get_lake_record(lake_id)

    if lake_record is None:
        return None

    payload = {
        "lake_id": normalize_lake_id(lake_record["Lake_ID"]),
        "catchment_id": catchment_id,
        "lake_label": "Lake " + normalize_lake_id(lake_record["Lake_ID"]) if not pd.isna(lake_record["Lake_ID"]) else "Unknown lake",
        "lake": {
            "type": "Feature",
            "properties": {
                "lake_id": normalize_lake_id(lake_record["Lake_ID"])
            },
            "geometry": lake_record.geometry.__geo_interface__
        } if lake_record.geometry is not None and not lake_record.geometry.is_empty else None
    }

    if catchment_id is None:
        payload["catchment"] = None
        return payload

    catchment_shape = get_catchment_shape(catchment_id)
    payload["catchment"] = {
        "type": "Feature",
        "properties": {"catchment_id": catchment_id},
        "geometry": catchment_shape.__geo_interface__
    } if catchment_shape is not None else None
    return payload


def get_clipped_lakes_gdf(catchment_id: str):
    require_geospatial_runtime()
    catchment_shape = get_catchment_shape(catchment_id)
    if catchment_shape is None:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    lakes_gdf = load_lakes_dataset()
    if lakes_gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    minx, miny, maxx, maxy = catchment_shape.bounds
    candidate_lakes = lakes_gdf.cx[minx:maxx, miny:maxy]
    if candidate_lakes.empty:
        return candidate_lakes.copy()

    catchment_gdf = gpd.GeoDataFrame(
        [{"catchment_id": str(catchment_id), "geometry": catchment_shape}],
        geometry="geometry",
        crs="EPSG:4326"
    )

    clipped_lakes = gpd.overlay(candidate_lakes, catchment_gdf, how="intersection", keep_geom_type=False)
    return clipped_lakes


def build_lakes_geojson(catchment_id: str):
    demo_lookup = load_demo_lakes_by_catchment()
    if str(catchment_id) in demo_lookup:
        return demo_lookup[str(catchment_id)]

    clipped_lakes = get_clipped_lakes_gdf(catchment_id)
    if clipped_lakes.empty:
        return {"type": "FeatureCollection", "features": []}

    clipped_lakes = clipped_lakes[["Lake_ID", "geometry"]].copy()
    return json.loads(clipped_lakes.to_json())


def build_lake_indicators(catchment_id: str):
    demo_summary = load_demo_lake_summary_by_catchment()
    if str(catchment_id) in demo_summary:
        return demo_summary[str(catchment_id)]

    catchment_shape = get_catchment_shape(catchment_id)
    if catchment_shape is None:
        return {
            "lake_coverage_percent": 0.0,
            "water_insight": "Catchment geometry unavailable"
        }

    catchment_gdf = gpd.GeoDataFrame(
        [{"catchment_id": str(catchment_id), "geometry": catchment_shape}],
        geometry="geometry",
        crs="EPSG:4326"
    )
    clipped_lakes = get_clipped_lakes_gdf(catchment_id)

    metric_crs = get_metric_crs()
    catchment_metric = catchment_gdf.to_crs(metric_crs)
    catchment_area = float(catchment_metric.geometry.area.iloc[0])

    lake_coverage_percent = 0.0

    if not clipped_lakes.empty:
        lakes_metric = clipped_lakes.to_crs(metric_crs)
        total_lake_area = float(lakes_metric.geometry.area.sum())
        if catchment_area > 0:
            lake_coverage_percent = (total_lake_area / catchment_area) * 100.0

    if lake_coverage_percent >= 5:
        water_insight = "Water-rich area"
    elif clipped_lakes.empty:
        water_insight = "No lake detected in this catchment"
    else:
        water_insight = "Limited lake presence"

    return {
        "lake_coverage_percent": round(lake_coverage_percent, 2),
        "water_insight": water_insight
    }


def should_serve_frontend():
    return os.getenv("SERVE_FRONTEND", "").strip().lower() in {"1", "true", "yes", "on"}


@app.route("/overlays/<path:filename>", methods=["GET"])
def serve_overlay(filename: str):
    if (DEMO_OVERLAYS_DIR / filename).exists():
        return send_from_directory(DEMO_OVERLAYS_DIR, filename)
    if (OVERLAY_DIR / filename).exists():
        return send_from_directory(OVERLAY_DIR, filename)
    if (LAKE_CCI_OVERLAY_DIR / filename).exists():
        return send_from_directory(LAKE_CCI_OVERLAY_DIR, filename)
    return send_from_directory(AOD_OVERLAY_DIR, filename)


@app.route("/query", methods=["GET"])
def query_data():
    try:
        print(
            "[query_debug] raw_request=",
            {
                "start_date": request.args.get("start_date"),
                "end_date": request.args.get("end_date"),
                "aggregation": request.args.get("aggregation"),
                "catchment_id": request.args.get("catchment_id"),
                "lake_id": request.args.get("lake_id"),
                "url": request.url,
            }
        )
        df = load_dataset()
        requested_id = request.args.get("catchment_id")
        requested_lake_id = request.args.get("lake_id")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        aggregation = normalize_aggregation_mode(request.args.get("aggregation"))
        selected_variables = parse_requested_variables(request.args.get("variables"))

        if not requested_id or not start_date or not end_date:
            return jsonify({
                "error": "Missing required query parameters: catchment_id, start_date, end_date"
            }), 400

        requested_id = str(requested_id)

        try:
            start_timestamp = pd.to_datetime(start_date)
            end_timestamp = pd.to_datetime(end_date)
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid date format. Expected YYYY-MM-DD."
            }), 400

        if start_timestamp > end_timestamp:
            return jsonify({
                "error": "start_date must be earlier than or equal to end_date."
            }), 400

        selected_period = None
        if aggregation == "10days":
            selected_day = int(start_timestamp.day)
            if selected_day <= 10:
                selected_period = "dekad-1"
            elif selected_day <= 20:
                selected_period = "dekad-2"
            else:
                selected_period = "dekad-3"

        print(
            "[query_debug] selected_date=",
            start_timestamp.strftime("%Y-%m-%d"),
            "end_date=",
            end_timestamp.strftime("%Y-%m-%d"),
            "aggregation=",
            aggregation,
            "selected_period=",
            selected_period,
        )

        print("Requested ID:", requested_id)

        if requested_id not in df["catchment_id"].values:
            print("Filtered rows:", 0)
            return jsonify(build_safe_analysis_response(
                requested_id,
                start_date,
                end_date,
                f"Unknown catchment_id: {requested_id}",
                summary={
                    "lake_coverage_percent": 0.0,
                    "water_insight": "Catchment not found"
                },
                selected_variables=selected_variables,
                aggregation=aggregation
            ))

        print("Available IDs:", df["catchment_id"].unique()[:10])

        subset = df[
            (df["catchment_id"] == requested_id)
            & (df["date"] >= start_timestamp)
            & (df["date"] <= end_timestamp)
        ].copy()
        print("Filtered rows:", len(subset))

        try:
            analysis_records = build_analysis_records(
                df,
                requested_id,
                start_timestamp,
                end_timestamp
            )
            analysis_records = resample_analysis_records(
                analysis_records,
                aggregation,
                start_timestamp,
                end_timestamp
            )
            print(
                "[query_debug] analysis_records_summary=",
                {
                    "count": len(analysis_records),
                    "dates": [
                        pd.to_datetime(value).strftime("%Y-%m-%d")
                        for value in analysis_records["date"].tolist()
                    ] if "date" in analysis_records.columns else [],
                    "records": serialize_records(analysis_records, aggregation),
                }
            )
        except Exception as error:
            app.logger.warning("Analysis record assembly failed for catchment=%s: %s", requested_id, error)
            analysis_records = pd.DataFrame([build_safe_analysis_record(requested_id, start_date)])

        try:
            overlay = resolve_overlay_from_demo_manifest(
                "catchment_overlays",
                "burned_area",
                requested_id,
                start_date,
                end_date
            ) if "burned_area" in selected_variables else None
        except Exception as error:
            app.logger.warning("Burned overlay resolution failed for catchment=%s: %s", requested_id, error)
            overlay = None
        print(f"[analysis] catchment_id={requested_id} overlay_response={overlay}")

        try:
            temperature_overlay = resolve_overlay_from_demo_manifest(
                "catchment_overlays",
                "temperature",
                requested_id,
                start_date,
                end_date
            ) if "temperature" in selected_variables else None
        except Exception as error:
            app.logger.warning("Temperature overlay resolution failed for catchment=%s: %s", requested_id, error)
            temperature_overlay = None

        try:
            aod_overlay = resolve_overlay_from_demo_manifest(
                "catchment_overlays",
                "aod",
                requested_id,
                start_date,
                end_date
            ) if "aod" in selected_variables else None
        except Exception as error:
            app.logger.warning("AOD overlay resolution failed for catchment=%s: %s", requested_id, error)
            aod_overlay = None

        try:
            chla_overlay = resolve_overlay_from_demo_manifest(
                "lake_overlays",
                "chla",
                requested_lake_id,
                start_date,
                end_date
            ) if "chla" in selected_variables else None
        except Exception as error:
            app.logger.warning("CHLA overlay resolution failed for lake=%s: %s", requested_lake_id, error)
            chla_overlay = None

        try:
            lswt_overlay = resolve_overlay_from_demo_manifest(
                "lake_overlays",
                "lake_surface_water_temperature",
                requested_lake_id,
                start_date,
                end_date
            ) if "lake_surface_water_temperature" in selected_variables else None
        except Exception as error:
            app.logger.warning("LSWT overlay resolution failed for lake=%s: %s", requested_lake_id, error)
            lswt_overlay = None

        try:
            tsm_overlay = resolve_overlay_from_demo_manifest(
                "lake_overlays",
                "tsm",
                requested_lake_id,
                start_date,
                end_date
            ) if "tsm" in selected_variables else None
        except Exception as error:
            app.logger.warning("TSM overlay resolution failed for lake=%s: %s", requested_lake_id, error)
            tsm_overlay = None

        try:
            summary = build_lake_indicators(requested_id)
        except Exception as error:
            app.logger.warning("Lake summary build failed for catchment=%s: %s", requested_id, error)
            summary = {
                "lake_coverage_percent": 0.0,
                "water_insight": "Analysis summary unavailable"
            }

        print(df.columns)
        print("Returning rows:", len(analysis_records))
        print("land_cover available:", "land_cover" in analysis_records.columns)
        print(json.dumps(serialize_records(analysis_records, aggregation)[:2], indent=2))
        return jsonify({
            "records": serialize_records(analysis_records, aggregation),
            "overlay": overlay,
            "temperature_overlay": temperature_overlay,
            "aod_overlay": aod_overlay,
            "chla_overlay": chla_overlay,
            "lswt_overlay": lswt_overlay,
            "tsm_overlay": tsm_overlay,
            "selected_variables": selected_variables,
            "aggregation": aggregation,
            "summary": summary
        })
    except Exception as error:
        app.logger.exception("Query request failed")
        return jsonify(build_safe_analysis_response(
            request.args.get("catchment_id") or "",
            request.args.get("start_date"),
            request.args.get("end_date"),
            "Backend failed to process the analysis request.",
            summary={
                "lake_coverage_percent": 0.0,
                "water_insight": "Analysis unavailable"
            },
            selected_variables=parse_requested_variables(request.args.get("variables")),
            aggregation=normalize_aggregation_mode(request.args.get("aggregation"))
        )), 200


@app.route("/lakes", methods=["GET"])
def lakes_data():
    catchment_id = request.args.get("catchment_id")
    if catchment_id is None:
        return jsonify({"type": "FeatureCollection", "features": []})

    return jsonify(build_lakes_geojson(str(catchment_id)))


@app.route("/lakes-overview", methods=["GET"])
def lakes_overview():
    return jsonify(build_lakes_overview_geojson())


@app.route("/lake-selection", methods=["GET"])
def lake_selection():
    lake_id = request.args.get("lake_id")
    if not lake_id:
        return jsonify({}), 400

    payload = build_lake_selection_payload(str(lake_id))
    if payload is None:
        return jsonify({}), 404

    return jsonify(payload)


@app.route("/land-cover", methods=["GET"])
def land_cover_lookup():
    demo_lookup = load_demo_land_cover_by_catchment()
    if demo_lookup:
        return jsonify(demo_lookup)

    df = load_dataset()
    if "land_cover" not in df.columns:
        return jsonify({})

    lookup = {}

    for catchment_id, values in df.groupby("catchment_id")["land_cover"]:
        valid_values = values.dropna()
        if valid_values.empty:
            lookup[catchment_id] = None
            continue

        lookup[catchment_id] = int(valid_values.mode().iloc[0])

    return jsonify(lookup)


@app.route("/", defaults={"path": ""}, methods=["GET"])
@app.route("/<path:path>", methods=["GET"])
def serve_frontend(path: str):
    if not should_serve_frontend():
        return jsonify({"error": "Frontend serving is disabled for this environment."}), 404

    requested_path = FRONTEND_DIR / path
    if path and requested_path.is_file():
        return send_from_directory(FRONTEND_DIR, path)

    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000"))),
        debug=os.getenv("FLASK_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
