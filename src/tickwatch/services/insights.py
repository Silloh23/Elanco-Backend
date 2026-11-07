"""Small pure analytics helpers for anomalies and baseline forecasts."""

import calendar
from collections.abc import Sequence
from datetime import datetime
from statistics import mean, pstdev

MIN_NON_ZERO_POINTS = 9


def non_zero_point_count(counts: Sequence[int]) -> int:
    """Count periods with observed events for sparse-series guards."""
    return sum(count > 0 for count in counts)


def month_of_year_averages(
    rows: Sequence[dict[str, int | str]],
) -> list[dict[str, int | float | str | None]]:
    """Average monthly counts for each calendar month across covered years."""
    if not rows:
        return []
    parsed = [datetime.fromisoformat(str(row["period"])) for row in rows]
    start = min(parsed).year * 12 + min(parsed).month - 1
    end = max(parsed).year * 12 + max(parsed).month - 1
    counts = {
        datetime.fromisoformat(str(row["period"])).year * 12
        + datetime.fromisoformat(str(row["period"])).month
        - 1: int(row["count"])
        for row in rows
    }
    result: list[dict[str, int | float | str | None]] = []
    for month in range(1, 13):
        eligible = [index for index in range(start, end + 1) if index % 12 + 1 == month]
        average = (
            round(sum(counts.get(index, 0) for index in eligible) / len(eligible), 2)
            if eligible
            else None
        )
        result.append(
            {
                "month": month,
                "month_name": calendar.month_name[month],
                "average_count": average,
                "years": len(eligible),
            }
        )
    return result


def anomaly_points(
    counts: Sequence[int], threshold: float = 2.0, window: int = 8
) -> list[dict[str, float | int]]:
    """Flag observations outside a rolling historical z-score threshold."""
    flags: list[dict[str, float | int]] = []
    for index in range(window, len(counts)):
        history = counts[max(0, index - window) : index]
        deviation = pstdev(history)
        expected = mean(history)
        if deviation == 0:
            score = threshold if counts[index] > expected else 0.0
        else:
            score = (counts[index] - expected) / deviation
        if score >= threshold:
            flags.append(
                {
                    "index": index,
                    "count": counts[index],
                    "expected": expected,
                    "z_score": score,
                }
            )
    return flags


def seasonal_forecast(counts: Sequence[int], periods: int = 4) -> list[float]:
    """Repeat the latest four observations as a transparent naive forecast."""
    if not counts:
        return [0.0] * periods
    baseline = list(counts[-4:])
    return [float(baseline[index % len(baseline)]) for index in range(periods)]
