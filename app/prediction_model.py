"""
ARIMA-based prediction model for vital signs forecasting.
Uses historical data points to predict next values via
Autoregressive Integrated Moving Average (ARIMA) modeling.
"""
import numpy as np
import pandas as pd
from typing import Optional
import warnings

warnings.filterwarnings("ignore")


def _try_arima(series: pd.Series, steps: int, vital: str) -> tuple:
    """
    Attempt ARIMA forecast with vital-specific orders.
    Returns (predictions, order_used) or (None, None).
    """
    orders_by_vital = {
        "spo2": [
            (1, 0, 1),   # ARMA(1,1) — tight baseline with sensor noise
            (1, 0, 0),   # AR(1) — simple baseline persistence
        ],
        "hr": [
            (1, 1, 0),   # ARI(1,1) — handles non-stationary baseline shifts
            (2, 1, 2),   # ARIMA(2,1,2) — second-order momentum for rapid changes
            (1, 0, 1),   # ARMA fallback
        ],
        "temp": [
            (1, 0, 0),   # AR(1) — slow thermal progression
            (1, 1, 0),   # ARI(1,1) — tracks continuous thermal drift
        ],
        "sys_bp": [
            (1, 1, 0),   # ARI(1,1) — tracks blood pressure shifts
            (1, 0, 1),   # ARMA fallback
        ],
        "dia_bp": [
            (1, 1, 0),   # ARI(1,1) — tracks diastolic pressure shifts
            (1, 0, 1),   # ARMA fallback
        ],
    }

    orders = orders_by_vital.get(vital, [(1, 0, 0), (1, 0, 1)])

    from statsmodels.tsa.arima.model import ARIMA

    for order in orders:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ARIMA(series, order=order)
                fitted = model.fit(method_kwargs={"maxiter": 200})
                forecast = fitted.forecast(steps=steps)
                predicted = [round(float(v), 2) for v in forecast]

                # Add realistic variation using residual bootstrapping
                residuals = fitted.resid
                if len(residuals) > 2:
                    resid_std = float(np.std(residuals))
                    noise_scale = resid_std * 0.25
                    np.random.seed(42)
                    predicted = [
                        round(float(v + np.random.normal(0, noise_scale)), 2)
                        for v in predicted
                    ]

                return (predicted, order)
        except Exception:
            continue

    return (None, None)


def _poly_fallback(data: list, steps: int) -> list:
    """Polynomial regression fallback when ARIMA cannot converge."""
    arr = np.array(data, dtype=float)
    n = len(arr)
    x = np.arange(max(0, n - 100), n, dtype=float)
    y = arr[-len(x):] if len(x) < n else arr

    weights = np.linspace(0.5, 1.5, len(x))
    try:
        coeffs = np.polyfit(x - x[0], y, min(2, len(x) - 1), w=weights)
        poly = np.poly1d(coeffs)
    except Exception:
        slope = (y[-1] - y[0]) / max(len(y) - 1, 1)
        poly = np.poly1d([slope, y[-1] - slope * (x[-1] - x[0])])

    last_x = x[-1] - x[0]
    future_x = np.arange(last_x + 1, last_x + steps + 1)
    predictions = poly(future_x)

    residuals = y - poly(x - x[0])
    noise_std = max(float(np.std(residuals)) * 0.2, 0.01)
    np.random.seed(42)

    return [round(float(p + np.random.normal(0, noise_std)), 2) for p in predictions]


def predict_vitals(
    spo2_history: list,
    hr_history: list,
    temp_history: list,
    sys_bp_history: list = None,
    dia_bp_history: list = None,
    steps: int = 20,
) -> dict:
    """
    ARIMA-based prediction of next `steps` vital sign values.
    """
    results = {}
    arima_orders_used = {}

    vitals_to_predict = [
        ("spo2", spo2_history or []),
        ("hr", hr_history or []),
        ("temp", temp_history or []),
        ("sys_bp", sys_bp_history or []),
        ("dia_bp", dia_bp_history or []),
    ]

    for name, history in vitals_to_predict:
        try:
            if not history or len(history) < 5:
                val = float(history[-1]) if history else 0.0
                results[name + "_predictions"] = [round(val, 2)] * steps
                arima_orders_used[name] = "insufficient_data"
                continue

            series = pd.Series([float(v) for v in history])

            arima_result, order_used = _try_arima(series, steps, name)

            if arima_result is not None:
                results[name + "_predictions"] = arima_result
                arima_orders_used[name] = f"ARIMA{order_used}"
            else:
                results[name + "_predictions"] = _poly_fallback(history, steps)
                arima_orders_used[name] = "poly_fallback"

        except Exception:
            val = float(history[-1]) if history else 0.0
            results[name + "_predictions"] = [round(val, 2)] * steps
            arima_orders_used[name] = "error"

    results["arima_orders"] = arima_orders_used
    results["confidence_intervals"] = _compute_confidence(results.get("spo2_predictions", []))

    return results


def _compute_confidence(predictions: list) -> list:
    """Pseudo-confidence bands widening with prediction horizon."""
    if not predictions:
        return []
    ci = []
    for i, pred in enumerate(predictions):
        margin = round(pred * 0.03 * (1 + i * 0.1), 2)
        ci.append({
            "lower": round(pred - margin, 2),
            "upper": round(pred + margin, 2),
        })
    return ci
