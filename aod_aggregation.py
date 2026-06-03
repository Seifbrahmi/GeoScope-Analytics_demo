from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask


RASTER_DIR = Path("data/AOD_Exports")
CATCHMENTS_PATH = Path("data/Ancillary/global_catchments_cci/global_catchments_cci.shp")
OUTPUT_PATH = Path("backend/outputs/aod_timeseries.csv")


def extract_date(raster_path: Path) -> str:
    parts = raster_path.stem.split("_")
    digit_parts = [part for part in parts if part.isdigit()]

    if len(digit_parts) >= 2:
        year = digit_parts[-2]
        month = digit_parts[-1].zfill(2)
        return f"{year}-{month}"

    return "unknown"


def main():
    print("Starting AOD aggregation...")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    catchments = gpd.read_file(CATCHMENTS_PATH)
    catchments = catchments.cx[-170:-50, 10:80]
    catchments = catchments.to_crs(epsg=6933)
    print(f"Number of catchments being processed: {len(catchments)}")

    raster_files = sorted(RASTER_DIR.glob("*.tif"))
    print(f"Number of AOD raster files: {len(raster_files)}")

    print("\nRaster files found:")
    for raster_path in raster_files:
        print(f"- {raster_path.name}")

    if not raster_files:
        print(f"Warning: no raster files found in {RASTER_DIR}")
        return

    with rasterio.open(raster_files[0]) as src:
        catchments_mask = catchments.to_crs(src.crs)

    results = []
    total_files = len(raster_files)

    for file_index, raster_path in enumerate(raster_files, start=1):
        print(f"\nProcessing file {file_index}/{total_files}: {raster_path.name}")

        date = extract_date(raster_path)
        print(f"Extracted date: {date}")

        with rasterio.open(raster_path) as src:
            total = len(catchments)

            for i, idx in enumerate(catchments.index):
                if i == 0 or (i + 1) % 100 == 0 or (i + 1) == total:
                    print(f"Processing catchment {i+1}/{total}")

                geom_mask = catchments_mask.loc[idx, "geometry"]
                aod = np.nan

                if geom_mask is not None and not geom_mask.is_empty:
                    try:
                        out_image, _ = mask(src, [geom_mask], crop=True, filled=False)
                        band = out_image[0]

                        if band.size != 0:
                            if np.ma.isMaskedArray(band):
                                data = band.filled(np.nan).astype(float)
                            else:
                                data = band.astype(float)

                            if src.nodata is not None:
                                data[data == src.nodata] = np.nan

                            finite_values = data[np.isfinite(data)]
                            if finite_values.size != 0:
                                aod = float(np.nanmean(finite_values))
                    except ValueError:
                        aod = np.nan

                results.append(
                    {
                        "catchment_id": idx,
                        "date": date,
                        "aod": aod,
                    }
                )

    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_PATH, index=False)

    print("\nDone!")
    print(f"Results saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
