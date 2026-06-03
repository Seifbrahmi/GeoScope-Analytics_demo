from pathlib import Path

import pandas as pd
from spatial_aggregation import build_land_cover_lookup


BURNT_AREA_PATH = Path("backend/outputs/burned_area_timeseries.csv")
RAINFALL_PATH = Path("backend/outputs/rainfall_timeseries.csv")
TEMPERATURE_PATH = Path("backend/outputs/temperature_timeseries.csv")
AOD_PATH = Path("backend/outputs/aod_timeseries.csv")
LAKE_CCI_PATH = Path("backend/outputs/lake_cci_timeseries.csv")
FINAL_DATASET_PATH = Path("backend/outputs/final_dataset.csv")


def ensure_land_cover_column(fire: pd.DataFrame) -> pd.DataFrame:
    if "land_cover" in fire.columns:
        return fire

    print("land_cover missing from burned_area_timeseries.csv; recomputing from land cover rasters...")
    land_cover_lookup = build_land_cover_lookup()
    land_cover_df = pd.DataFrame(
        [
            {
                "catchment_id": catchment_id,
                "land_cover": pd.NA if pd.isna(land_cover) else int(land_cover),
            }
            for catchment_id, land_cover in land_cover_lookup.items()
        ]
    )

    fire = pd.merge(fire, land_cover_df, on="catchment_id", how="left")
    fire.to_csv(BURNT_AREA_PATH, index=False)
    print("Updated burned area timeseries with land_cover.")
    return fire


def main():
    fire = pd.read_csv(BURNT_AREA_PATH)
    rain = pd.read_csv(RAINFALL_PATH)
    temperature = pd.read_csv(TEMPERATURE_PATH)
    aod = pd.read_csv(AOD_PATH) if AOD_PATH.exists() else pd.DataFrame(columns=["catchment_id", "date", "aod"])
    lake_cci = (
        pd.read_csv(LAKE_CCI_PATH)
        if LAKE_CCI_PATH.exists()
        else pd.DataFrame(
            columns=[
                "catchment_id",
                "date",
                "chla",
                "lake_surface_water_temperature",
                "tsm",
            ]
        )
    )

    fire["catchment_id"] = pd.to_numeric(fire["catchment_id"], errors="coerce").astype("Int64")
    rain["catchment_id"] = pd.to_numeric(rain["catchment_id"], errors="coerce").astype("Int64")
    temperature["catchment_id"] = pd.to_numeric(temperature["catchment_id"], errors="coerce").astype("Int64")
    aod["catchment_id"] = pd.to_numeric(aod["catchment_id"], errors="coerce").astype("Int64")
    lake_cci["catchment_id"] = pd.to_numeric(lake_cci["catchment_id"], errors="coerce").astype("Int64")
    fire = ensure_land_cover_column(fire)

    df = pd.merge(fire, rain, on=["catchment_id", "date"])
    df = pd.merge(df, temperature, on=["catchment_id", "date"], how="left")
    df = pd.merge(df, aod, on=["catchment_id", "date"], how="left")
    df = pd.merge(df, lake_cci, on=["catchment_id", "date"], how="left")
    df["rainfall"] = df["rainfall"].fillna(0)
    df["temperature"] = pd.to_numeric(df["temperature"], errors="coerce")
    df["aod"] = pd.to_numeric(df["aod"], errors="coerce")
    df["chla"] = pd.to_numeric(df["chla"], errors="coerce")
    df["lake_surface_water_temperature"] = pd.to_numeric(
        df["lake_surface_water_temperature"],
        errors="coerce",
    )
    df["tsm"] = pd.to_numeric(df["tsm"], errors="coerce")

    if "land_cover" not in df.columns:
        df["land_cover"] = pd.NA

    df = df[
        [
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
    ]
    df.to_csv(FINAL_DATASET_PATH, index=False)

    print(f"Number of rows: {len(df)}")
    print("Columns:", df.columns.tolist())
    print("Missing land_cover values:", int(df["land_cover"].isna().sum()))
    print(df.head())


if __name__ == "__main__":
    main()
