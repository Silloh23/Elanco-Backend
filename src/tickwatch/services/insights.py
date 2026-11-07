"""Small pure analytics helpers for anomalies and baseline forecasts."""

from collections.abc import Sequence
from statistics import mean, pstdev


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
