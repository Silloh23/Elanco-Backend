"""Small pure analytics helpers for anomalies and baseline forecasts."""

import calendar
from collections.abc import Sequence
from datetime import datetime
from math import exp, lgamma, log
from statistics import mean, pstdev

MIN_NON_ZERO_POINTS = 9
SIGNIFICANCE_LEVEL = 0.05
GAMMA_EPSILON = 1e-12
GAMMA_FLOOR = 1e-300
GAMMA_MAX_ITERATIONS = 1000


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


def chi_square_monthly_test(
    rows: Sequence[dict[str, int | str]],
) -> dict[str, float | int | bool | str] | None:
    """Test uniform daily sighting rates across covered calendar months."""
    if not rows:
        return None
    parsed = [datetime.fromisoformat(str(row["period"])) for row in rows]
    start = min(parsed).year * 12 + min(parsed).month - 1
    end = max(parsed).year * 12 + max(parsed).month - 1
    counts = {
        datetime.fromisoformat(str(row["period"])).year * 12
        + datetime.fromisoformat(str(row["period"])).month
        - 1: int(row["count"])
        for row in rows
    }
    observed = [0] * 12
    exposure_days = [0] * 12
    for index in range(start, end + 1):
        year, month = divmod(index, 12)
        month += 1
        observed[month - 1] += counts.get(index, 0)
        exposure_days[month - 1] += calendar.monthrange(year, month)[1]
    active_months = [month for month in range(12) if exposure_days[month] > 0]
    total = sum(observed)
    if total == 0 or len(active_months) < 12:
        return None
    total_days = sum(exposure_days)
    expected = [total * exposure_days[month] / total_days for month in active_months]
    chi2 = sum(
        (observed[month] - expected[index]) ** 2 / expected[index]
        for index, month in enumerate(active_months)
    )
    degrees_of_freedom = len(active_months) - 1
    p_value = _chi_square_survival(chi2, degrees_of_freedom)
    significant = p_value < SIGNIFICANCE_LEVEL
    verdict = (
        "statistically significant seasonality at 5%"
        if significant
        else "no statistically significant seasonality at 5%"
    )
    return {
        "chi2": round(chi2, 4),
        "degrees_of_freedom": degrees_of_freedom,
        "p_value": p_value,
        "significant": significant,
        "verdict": verdict,
    }


def _chi_square_survival(chi2: float, degrees_of_freedom: int) -> float:
    """Calculate a chi-square upper-tail probability using regularized gamma Q."""
    return _regularized_gamma_q(degrees_of_freedom / 2, chi2 / 2)


def _regularized_gamma_q(shape: float, value: float) -> float:
    """Evaluate the regularized upper incomplete gamma function numerically."""
    if value == 0:
        return 1.0
    factor = exp(-value + shape * log(value) - lgamma(shape))
    if value < shape + 1:
        term = total = 1 / shape
        current_shape = shape
        for _ in range(GAMMA_MAX_ITERATIONS):
            current_shape += 1
            term *= value / current_shape
            total += term
            if abs(term) < abs(total) * GAMMA_EPSILON:
                break
        return min(1.0, max(0.0, 1 - total * factor))

    offset = value + 1 - shape
    coefficient = 1 / GAMMA_FLOOR
    denominator = 1 / offset if abs(offset) >= GAMMA_FLOOR else 1 / GAMMA_FLOOR
    fraction = denominator
    for index in range(1, GAMMA_MAX_ITERATIONS + 1):
        term = -index * (index - shape)
        offset += 2
        denominator = term * denominator + offset
        if abs(denominator) < GAMMA_FLOOR:
            denominator = GAMMA_FLOOR
        coefficient = offset + term / coefficient
        if abs(coefficient) < GAMMA_FLOOR:
            coefficient = GAMMA_FLOOR
        denominator = 1 / denominator
        delta = denominator * coefficient
        fraction *= delta
        if abs(delta - 1) < GAMMA_EPSILON:
            break
    return min(1.0, max(0.0, factor * fraction))


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
