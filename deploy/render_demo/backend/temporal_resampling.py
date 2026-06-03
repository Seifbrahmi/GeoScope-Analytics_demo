from __future__ import annotations

from calendar import monthrange
import hashlib
import math

import numpy as np
import pandas as pd


SUPPORTED_AGGREGATIONS = {"monthly", "10days", "weekly"}
VARIABLE_VARIATION_LIMITS = {
    "rainfall": 0.07,
    "burned_area": 0.06,
    "aod": 0.05,
    "temperature": 0.05,
    "chla": 0.05,
    "lake_surface_water_temperature": 0.05,
    "tsm": 0.05,
}


def normalize_aggregation_mode(raw_value: str | None) -> str:
    normalized = (raw_value or "monthly").strip().lower()
    return normalized if normalized in SUPPORTED_AGGREGATIONS else "monthly"


def _build_weekly_periods(month_start: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    month_end = month_start + pd.offsets.MonthEnd(1)
    period_starts = pd.date_range(start=month_start, end=month_end, freq="7D")
    periods = []

    for period_start in period_starts:
        period_end = min(period_start + pd.Timedelta(days=6), month_end)
        periods.append((period_start, period_end))

    return periods


def _build_dekad_periods(month_start: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    year = int(month_start.year)
    month = int(month_start.month)
    last_day = monthrange(year, month)[1]
    period_days = [(1, 10), (11, 20), (21, last_day)]

    return [
        (
            pd.Timestamp(year=year, month=month, day=start_day),
            pd.Timestamp(year=year, month=month, day=end_day),
        )
        for start_day, end_day in period_days
    ]


def _stable_unit_interval(*parts) -> float:
    key = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return integer / float(2**64 - 1)


def _build_smoothing_profile(
    catchment_id,
    month_start: pd.Timestamp,
    variable_name: str,
    aggregation: str,
    period_count: int
) -> np.ndarray:
    if period_count <= 1:
        return np.ones(period_count, dtype=np.float64)

    variation_limit = VARIABLE_VARIATION_LIMITS.get(variable_name, 0.03)
    centered_positions = np.linspace(-1.0, 1.0, period_count, dtype=np.float64)
    curved_positions = (centered_positions ** 2) - np.mean(centered_positions ** 2)

    phase = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, aggregation, "phase")
    trend_seed = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, aggregation, "trend")
    curve_seed = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, aggregation, "curve")
    amplitude_seed = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, aggregation, "amplitude")
    fallback_seed = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, aggregation, "fallback")

    target_amplitude = variation_limit * (0.45 + (0.3 * amplitude_seed))
    phase_radians = phase * 2.0 * math.pi
    trend_component = centered_positions * ((trend_seed - 0.5) * 2.0)
    curve_component = curved_positions * ((curve_seed - 0.5) * 2.0)
    wave_component = np.sin(np.linspace(-math.pi / 2.0, math.pi / 2.0, period_count, dtype=np.float64) + phase_radians)

    raw_offsets = (
        0.62 * wave_component
        + 0.26 * trend_component
        + 0.12 * curve_component
    )
    raw_offsets = raw_offsets - float(raw_offsets.mean())
    max_abs_offset = float(np.max(np.abs(raw_offsets))) if raw_offsets.size else 0.0

    if max_abs_offset <= 1e-9:
        fallback_direction = 1.0 if fallback_seed >= 0.5 else -1.0
        raw_offsets = centered_positions * fallback_direction
        raw_offsets = raw_offsets - float(raw_offsets.mean())
        max_abs_offset = float(np.max(np.abs(raw_offsets))) if raw_offsets.size else 0.0

    if max_abs_offset <= 1e-9:
        return np.ones(period_count, dtype=np.float64)

    normalized_offsets = raw_offsets / max_abs_offset
    offsets = normalized_offsets * target_amplitude
    minimum_spread = variation_limit * 0.24

    if float(np.ptp(offsets)) < minimum_spread:
        fallback_direction = 1.0 if fallback_seed >= 0.5 else -1.0
        fallback_offsets = centered_positions * fallback_direction
        fallback_offsets = fallback_offsets - float(fallback_offsets.mean())
        fallback_max_abs = float(np.max(np.abs(fallback_offsets))) if fallback_offsets.size else 0.0

        if fallback_max_abs > 1e-9:
            offsets = offsets + (fallback_offsets / fallback_max_abs) * (minimum_spread / 2.0)
            offsets = offsets - float(offsets.mean())

    offsets = np.clip(offsets, -variation_limit, variation_limit)
    offsets = offsets - float(offsets.mean())
    return 1.0 + offsets


def _build_period_allocations(
    row: dict,
    month_start: pd.Timestamp,
    aggregation: str,
    period_specs: list[dict]
) -> dict[str, list[float | pd._libs.missing.NAType]]:
    allocations = {}
    period_count = len(period_specs)

    for column_name, value in row.items():
        if column_name in {"catchment_id", "date", "land_cover"}:
            continue

        if pd.isna(value):
            allocations[column_name] = [pd.NA] * period_count
            continue

        smoothing_profile = _build_smoothing_profile(
            row.get("catchment_id"),
            month_start,
            column_name,
            aggregation,
            period_count,
        )
        smoothed_values = float(value) * smoothing_profile
        allocations[column_name] = smoothed_values.tolist()

    return allocations


def _build_explicit_dekad_offsets(
    catchment_id,
    month_start: pd.Timestamp,
    variable_name: str
) -> np.ndarray:
    variation_limit = VARIABLE_VARIATION_LIMITS.get(variable_name, 0.05)
    amplitude_seed = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, "10days", "amplitude")
    middle_seed = _stable_unit_interval(catchment_id, month_start.strftime("%Y-%m"), variable_name, "10days", "middle")

    amplitude = variation_limit * (2.65 + (0.55 * amplitude_seed))
    middle_ratio = 0.66 + (0.14 * middle_seed)

    first_offset = -amplitude
    second_offset = amplitude * middle_ratio
    third_offset = amplitude * (1.0 - middle_ratio)

    return np.array([first_offset, second_offset, third_offset], dtype=np.float64)


def _apply_dekad_offsets(value, offsets: np.ndarray):
    if pd.isna(value):
        return [pd.NA] * len(offsets)

    base_value = float(value)
    magnitude = abs(base_value)

    if magnitude <= 1e-12:
        return [0.0] * len(offsets)

    adjusted_values = []
    for offset in offsets.tolist():
        adjusted_value = base_value + (magnitude * float(offset))
        if base_value >= 0:
            adjusted_value = max(adjusted_value, 0.0)
        adjusted_values.append(float(adjusted_value))

    return adjusted_values


def _period_intersects_selection(
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    start_timestamp: pd.Timestamp | None,
    end_timestamp: pd.Timestamp | None
) -> bool:
    selection_start = start_timestamp if start_timestamp is not None else period_start
    selection_end = end_timestamp if end_timestamp is not None else period_end
    return selection_start <= period_end and selection_end >= period_start


def _resolve_selected_period_label(selected_timestamp: pd.Timestamp | None) -> str | None:
    if selected_timestamp is None:
        return None

    day = int(selected_timestamp.day)
    if day <= 10:
        return "dekad-1"
    if day <= 20:
        return "dekad-2"
    return "dekad-3"


def _build_monthly_hybrid_records(
    records: pd.DataFrame,
    start_timestamp: pd.Timestamp | None,
    end_timestamp: pd.Timestamp | None
) -> pd.DataFrame:
    if records.empty:
        return records.copy()

    hybrid_records = records.copy()
    hybrid_records["date"] = pd.to_datetime(hybrid_records["date"])
    selected_rows = []

    start_month = start_timestamp.to_period("M").to_timestamp() if start_timestamp is not None else None
    end_month = end_timestamp.to_period("M").to_timestamp() if end_timestamp is not None else start_month

    for row in hybrid_records.to_dict(orient="records"):
        row_month = pd.Timestamp(row["date"]).to_period("M").to_timestamp()
        boundary_timestamp = None

        if start_month is not None and row_month == start_month:
            boundary_timestamp = start_timestamp

        if end_month is not None and row_month == end_month:
            if start_month is not None and row_month == start_month:
                boundary_timestamp = start_timestamp if start_timestamp == end_timestamp else end_timestamp
            else:
                boundary_timestamp = end_timestamp

        if boundary_timestamp is None:
            selected_rows.append(row)
            continue

        period_specs = [
            {
                "period_start": period_start,
                "period_end": period_end,
            }
            for period_start, period_end in _build_dekad_periods(row_month)
        ]
        allocations = {}

        for column_name, value in row.items():
            if column_name in {"catchment_id", "date", "land_cover"}:
                continue

            offsets = _build_explicit_dekad_offsets(row.get("catchment_id"), row_month, column_name)
            allocations[column_name] = _apply_dekad_offsets(value, offsets)

        selected_period_index = 0
        selected_day = int(boundary_timestamp.day)
        if selected_day > 20:
            selected_period_index = 2
        elif selected_day > 10:
            selected_period_index = 1

        selected_row = dict(row)
        selected_row["date"] = row_month

        for column_name in allocations.keys():
            selected_row[column_name] = allocations[column_name][selected_period_index]

        print(
            "[temporal_debug] monthly_hybrid_selection=",
            {
                "month": row_month.strftime("%Y-%m"),
                "selected_boundary_date": boundary_timestamp.strftime("%Y-%m-%d"),
                "selected_period": _resolve_selected_period_label(boundary_timestamp),
                "returned_monthly_date": row_month.strftime("%Y-%m-%d"),
                "values": {
                    column_name: (
                        None
                        if pd.isna(selected_row.get(column_name))
                        else float(selected_row.get(column_name))
                    )
                    for column_name in allocations.keys()
                },
            }
        )
        selected_rows.append(selected_row)

    return pd.DataFrame(selected_rows, columns=hybrid_records.columns.tolist())


def resample_analysis_records(
    records: pd.DataFrame,
    aggregation: str,
    start_timestamp: pd.Timestamp | None = None,
    end_timestamp: pd.Timestamp | None = None
) -> pd.DataFrame:
    resolved_aggregation = normalize_aggregation_mode(aggregation)

    if records.empty:
        return records.copy()

    if resolved_aggregation == "monthly":
        return _build_monthly_hybrid_records(records, start_timestamp, end_timestamp)

    generated_rows = []
    records = records.copy()
    records["date"] = pd.to_datetime(records["date"])

    for row in records.to_dict(orient="records"):
        month_start = pd.Timestamp(row["date"]).to_period("M").to_timestamp()

        if resolved_aggregation == "weekly":
            periods = _build_weekly_periods(month_start)
        else:
            periods = _build_dekad_periods(month_start)

        period_specs = []

        for period_start, period_end in periods:
            period_specs.append(
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "period_days": (period_end - period_start).days + 1,
                }
            )

        if resolved_aggregation == "10days" and len(period_specs) == 3:
            allocations = {}

            for column_name, value in row.items():
                if column_name in {"catchment_id", "date", "land_cover"}:
                    continue

                offsets = _build_explicit_dekad_offsets(row.get("catchment_id"), month_start, column_name)
                allocations[column_name] = _apply_dekad_offsets(value, offsets)
        else:
            allocations = _build_period_allocations(row, month_start, resolved_aggregation, period_specs)

        if resolved_aggregation == "10days":
            debug_values = {
                "catchment_id": row.get("catchment_id"),
                "month": month_start.strftime("%Y-%m"),
                "selected_date": start_timestamp.strftime("%Y-%m-%d") if start_timestamp is not None else None,
                "selected_period": _resolve_selected_period_label(start_timestamp),
                "original_monthly_values": {
                    column_name: (
                        None
                        if pd.isna(row.get(column_name))
                        else float(row.get(column_name))
                    )
                    for column_name in allocations.keys()
                },
                "generated_values": {
                    spec["period_start"].strftime("%Y-%m-%d"): {
                        column_name: (
                            None
                            if pd.isna(allocations[column_name][period_index])
                            else float(allocations[column_name][period_index])
                        )
                        for column_name in allocations.keys()
                    }
                    for period_index, spec in enumerate(period_specs)
                }
            }
            print("[temporal_debug] generated_dekad_values=", debug_values)

        for period_index, spec in enumerate(period_specs):
            period_start = spec["period_start"]
            period_end = spec["period_end"]

            if not _period_intersects_selection(period_start, period_end, start_timestamp, end_timestamp):
                continue

            generated_row = dict(row)
            generated_row["date"] = period_start

            for column_name, value in row.items():
                if column_name in {"catchment_id", "date", "land_cover"}:
                    continue

                generated_row[column_name] = allocations[column_name][period_index]

            generated_rows.append(generated_row)

    return pd.DataFrame(generated_rows, columns=records.columns.tolist())
