import json
import os
from typing import Tuple, List, Optional
from app.config import PARAMETER_PATH

# Load parameter.json thresholds at service initialization
_VITAL_THRESHOLDS = []
if PARAMETER_PATH.exists():
    with open(PARAMETER_PATH, "r", encoding="utf-8") as f:
        _VITAL_THRESHOLDS = json.load(f).get("vital_thresholds", [])


def get_threshold_for_age(age: Optional[int]) -> dict:
    """Return the threshold block matching the patient's age, or default adult."""
    if not _VITAL_THRESHOLDS:
        return {}

    if age is None:
        for t in _VITAL_THRESHOLDS:
            if t.get("id") == "young_middle_adult":
                return t
        return _VITAL_THRESHOLDS[min(4, len(_VITAL_THRESHOLDS) - 1)]

    for t in _VITAL_THRESHOLDS:
        r = t.get("age_range", {})
        lo = r.get("min", 0)
        hi = r.get("max")
        if r.get("unit") == "months":
            age_months = age * 12
            hi_val = hi if hi is not None else float("inf")
            if lo <= age_months <= hi_val:
                return t
        else:
            if hi is None:
                if age >= lo:
                    return t
            elif lo <= age <= hi:
                return t

    # Fallback
    for t in _VITAL_THRESHOLDS:
        if t.get("id") == "young_middle_adult":
            return t
    return _VITAL_THRESHOLDS[min(4, len(_VITAL_THRESHOLDS) - 1)]


def _eval_spec_item(value: float, item: dict) -> bool:
    """Safely check an operator/value rule dict."""
    if not isinstance(item, dict):
        return False
    op = item.get("operator", ">")
    target = item.get("value")
    if target is None:
        return False
    if op == "<" and value < target:
        return True
    if op == "<=" and value <= target:
        return True
    if op == ">" and value > target:
        return True
    if op == ">=" and value >= target:
        return True
    return False


def eval_vital_range(value: Optional[float], spec: dict) -> str:
    """Evaluate a single vital value against spec rules. Returns 'green', 'yellow', or 'red'."""
    if value is None or not spec:
        return "green"

    # critical_low
    cl = spec.get("critical_low")
    if cl:
        items = cl if isinstance(cl, list) else [cl]
        for item in items:
            if _eval_spec_item(value, item):
                return "red"

    # crisis_high / critical_high
    for key in ("crisis_high", "critical_high"):
        ch = spec.get(key)
        if ch:
            items = ch if isinstance(ch, list) else [ch]
            for item in items:
                if _eval_spec_item(value, item):
                    return "red"

    # at_risk_low
    al = spec.get("at_risk_low")
    if al and isinstance(al, dict) and "min" in al and al["min"] <= value <= al.get("max", float("inf")):
        return "yellow"

    # at_risk_high
    ah = spec.get("at_risk_high")
    if ah and isinstance(ah, dict) and "min" in ah and ah["min"] <= value <= ah.get("max", float("inf")):
        return "yellow"

    return "green"


def check_vitals_alert(
    age: Optional[int],
    hr: Optional[float],
    spo2: Optional[float],
    temp_val: Optional[float],
    sys_bp: Optional[float],
    dia_bp: Optional[float],
    sensor_error: bool = False
) -> Tuple[str, bool, List[str]]:
    """
    Check all vitals against parameter.json thresholds.
    Returns (led, is_alert, reasons) where led is 'green','yellow','red', or 'error'.
    """
    if sensor_error:
        return ("error", True, ["Sensor error: no finger detected or poor reading"])

    t = get_threshold_for_age(age)
    if not t:
        return ("green", False, [])

    reasons = []
    highest = "green"

    if hr is not None and "heart_rate_bpm" in t:
        level = eval_vital_range(float(hr), t["heart_rate_bpm"])
        if level == "red":
            reasons.append(f"HR:{int(hr)}")
            highest = "red"
        elif level == "yellow" and highest != "red":
            reasons.append(f"HR:{int(hr)}")
            highest = "yellow"

    if spo2 is not None and "spo2_percent" in t:
        level = eval_vital_range(float(spo2), t["spo2_percent"])
        if level == "red":
            reasons.append(f"SpO2:{int(spo2)}%")
            highest = "red"
        elif level == "yellow" and highest != "red":
            reasons.append(f"SpO2:{int(spo2)}%")
            highest = "yellow"

    if temp_val is not None and "temperature" in t:
        temp_spec = t["temperature"].get("celsius", t["temperature"]) if isinstance(t["temperature"], dict) else t["temperature"]
        level = eval_vital_range(float(temp_val), temp_spec)
        if level == "red":
            reasons.append(f"T:{temp_val:.1f}")
            highest = "red"
        elif level == "yellow" and highest != "red":
            reasons.append(f"T:{temp_val:.1f}")
            highest = "yellow"

    if sys_bp is not None and "sbp_mmHg" in t:
        level = eval_vital_range(float(sys_bp), t["sbp_mmHg"])
        if level == "red":
            reasons.append(f"SYS:{int(sys_bp)}")
            highest = "red"
        elif level == "yellow" and highest != "red":
            reasons.append(f"SYS:{int(sys_bp)}")
            highest = "yellow"

    if dia_bp is not None and "dbp_mmHg" in t:
        level = eval_vital_range(float(dia_bp), t["dbp_mmHg"])
        if level == "red":
            reasons.append(f"DIA:{int(dia_bp)}")
            highest = "red"
        elif level == "yellow" and highest != "red":
            reasons.append(f"DIA:{int(dia_bp)}")
            highest = "yellow"

    is_alert = highest in ("yellow", "red")
    return (highest, is_alert, reasons)
