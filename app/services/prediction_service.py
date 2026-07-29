from app.prediction_model import predict_vitals
from typing import Dict, List, Any


def get_vitals_predictions(
    spo2_history: List[float],
    hr_history: List[float],
    temp_history: List[float],
    sys_bp_history: List[float] = None,
    dia_bp_history: List[float] = None,
    steps: int = 20
) -> Dict[str, Any]:
    """
    Service wrapper for ARIMA / polynomial vitals forecasting.
    Sanitizes null values and returns predictions alongside confidence intervals.
    """
    clean_spo2 = [float(v) for v in (spo2_history or []) if v is not None]
    clean_hr = [float(v) for v in (hr_history or []) if v is not None]
    clean_temp = [float(v) for v in (temp_history or []) if v is not None]
    clean_sys_bp = [float(v) for v in (sys_bp_history or []) if v is not None]
    clean_dia_bp = [float(v) for v in (dia_bp_history or []) if v is not None]

    return predict_vitals(clean_spo2, clean_hr, clean_temp, clean_sys_bp, clean_dia_bp, steps=steps)
