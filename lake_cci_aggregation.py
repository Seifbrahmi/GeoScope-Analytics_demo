from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

from spatial_aggregation import load_catchments

try:
    import xarray as xr  # noqa: F401
    import rioxarray  # noqa: F401

    HAS_XARRAY_STACK = True
except ImportError:
    HAS_XARRAY_STACK = False


NETCDF_DIR = Path("data/lake_cci")
OUTPUT_PATH = Path("backend/outputs/lake_cci_timeseries.csv")
DEFAULT_GEOGRAPHIC_CRS = "EPSG:4326"

VARIABLE_CONFIGS = {
    "chla": {
        "subdataset": "chla",
        "convert": lambda values: values.astype(np.float32),
    },
    "lake_surface_water_temperature": {
        "subdataset": "lake_surface_water_temperature",
        "convert": lambda values: values.astype(np.float32) - 273.15,
    },
    "tsm": {
        "subdataset": "tsm",
        "convert": lambda values: values.astype(np.float32),
    },
}


def extract_date(netcdf_path: Path) -> str:
    match = re.search(r"(\d{8})", netcdf_path.stem)
    if not match:
        return "unknown"

    date_token = match.group(1)
    return f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:8]}"


def get_month_key(date_value: str) -> str:
    return date_value[:7] if date_value != "unknown" else "unknown"


def get_mask_crs(src) -> str:
    return str(src.crs) if src.crs else DEFAULT_GEOGRAPHIC_CRS


def get_catchments_by_crs():
    geographic_catchments = load_catchments().to_crs(epsg=4326)
    return geographic_catchments


def build_zone_raster(geographic_catchments, reference_path: Path):
    reference_subdataset = f"netcdf:{reference_path.as_posix()}:{VARIABLE_CONFIGS['chla']['subdataset']}"

    with rasterio.open(reference_subdataset) as src:
        zone_items = [
            (zone_index, int(catchment_id), geometry)
            for zone_index, (catchment_id, geometry) in enumerate(
                zip(geographic_catchments.index.tolist(), geographic_catchments.geometry.tolist()),
                start=1,
            )
            if geometry is not None and not geometry.is_empty
        ]
        zone_shapes = [(geometry, zone_index) for zone_index, _, geometry in zone_items]
        zone_raster = rasterize(
            zone_shapes,
            out_shape=(src.height, src.width),
            transform=src.transform,
            fill=0,
            all_touched=False,
            dtype="int32",
        )

        zone_lookup = {zone_index: catchment_id for zone_index, catchment_id, _ in zone_items}
        return zone_raster, zone_lookup, src.transform, src.height, src.width


def ensure_matching_grid(src, expected_transform, expected_height: int, expected_width: int):
    if src.height != expected_height or src.width != expected_width or src.transform != expected_transform:
        raise ValueError("LakeCCI source grid does not match the reference zone raster grid.")


def process_variable(
    raster_files: list[Path],
    variable_name: str,
    zone_raster: np.ndarray,
    zone_lookup: dict[int, int],
    expected_transform,
    expected_height: int,
    expected_width: int,
    monthly_stats: dict[tuple[int, str], dict[str, float]],
):
    config = VARIABLE_CONFIGS[variable_name]
    total_files = len(raster_files)
    zone_count = max(zone_lookup) if zone_lookup else 0

    for file_index, netcdf_path in enumerate(raster_files, start=1):
        date_value = extract_date(netcdf_path)
        if date_value == "unknown":
            continue

        month_key = get_month_key(date_value)
        subdataset_path = f"netcdf:{netcdf_path.as_posix()}:{config['subdataset']}"

        with rasterio.open(subdataset_path) as src:
            ensure_matching_grid(src, expected_transform, expected_height, expected_width)

            if file_index == 1 or file_index % 25 == 0 or file_index == total_files:
                print(
                    f"[LakeCCI] {variable_name}: processing file {file_index}/{total_files} "
                    f"({netcdf_path.name})"
                )

            data = src.read(1).astype(np.float32)
            if src.nodata is not None:
                data = np.where(data == src.nodata, np.nan, data)

            converted = VARIABLE_CONFIGS[variable_name]["convert"](data)
            valid_mask = np.isfinite(converted) & (zone_raster > 0)

            if not valid_mask.any():
                continue

            zone_ids = zone_raster[valid_mask].astype(np.int32)
            values = converted[valid_mask].astype(np.float64)
            zone_sums = np.bincount(zone_ids, weights=values, minlength=zone_count + 1)
            zone_counts = np.bincount(zone_ids, minlength=zone_count + 1)
            populated_zone_ids = np.nonzero(zone_counts)[0]

            for zone_id in populated_zone_ids.tolist():
                if zone_id == 0 or zone_id not in zone_lookup:
                    continue

                catchment_id = zone_lookup[zone_id]
                value = zone_sums[zone_id] / zone_counts[zone_id]
                stats_key = (catchment_id, month_key)
                monthly_stats[stats_key][f"{variable_name}_sum"] += value
                monthly_stats[stats_key][f"{variable_name}_count"] += 1


def build_output_frame(monthly_stats: dict[tuple[int, str], dict[str, float]]) -> pd.DataFrame:
    rows = []

    for (catchment_id, month_key), stats in sorted(monthly_stats.items()):
        row = {
            "catchment_id": catchment_id,
            "date": month_key,
        }
        has_value = False

        for variable_name in VARIABLE_CONFIGS:
            sum_key = f"{variable_name}_sum"
            count_key = f"{variable_name}_count"
            count_value = stats.get(count_key, 0)

            if count_value > 0:
                row[variable_name] = stats[sum_key] / count_value
                has_value = True
            else:
                row[variable_name] = np.nan

        if has_value:
            rows.append(row)

    return pd.DataFrame(rows)


def main():
    print("Starting LakeCCI aggregation...")
    if HAS_XARRAY_STACK:
        print("xarray/rioxarray detected; rasterio masking workflow will run with NetCDF-compatible dependencies available.")
    else:
        print("xarray/rioxarray not available; using rasterio-only LakeCCI aggregation fallback.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    raster_files = sorted(NETCDF_DIR.glob("*.nc"))
    print(f"Number of LakeCCI NetCDF files: {len(raster_files)}")

    if not raster_files:
        print(f"Warning: no NetCDF files found in {NETCDF_DIR}")
        return

    geographic_catchments = get_catchments_by_crs()
    print(f"Number of catchments being processed: {len(geographic_catchments)}")
    zone_raster, zone_lookup, expected_transform, expected_height, expected_width = build_zone_raster(
        geographic_catchments,
        raster_files[0],
    )
    print(f"Catchment zones rasterized: {len(zone_lookup)}")

    monthly_stats: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for variable_name in VARIABLE_CONFIGS:
        process_variable(
            raster_files,
            variable_name,
            zone_raster,
            zone_lookup,
            expected_transform,
            expected_height,
            expected_width,
            monthly_stats,
        )

    output_frame = build_output_frame(monthly_stats)
    output_frame.to_csv(OUTPUT_PATH, index=False)

    print("\nDone!")
    print("Columns:", output_frame.columns.tolist())
    print(output_frame.head())
    print(f"Results saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
