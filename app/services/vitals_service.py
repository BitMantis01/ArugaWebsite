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


def eval_vital_detail(value: Optional[float], spec: dict) -> Tuple[str, Optional[str]]:
    """
    Evaluate a single vital value against spec rules.
    Returns (level, direction) where level is 'green', 'yellow', or 'red', and direction is 'low' or 'high'.
    """
    if value is None or not spec:
        return ("green", None)

    # critical_low
    cl = spec.get("critical_low")
    if cl:
        items = cl if isinstance(cl, list) else [cl]
        for item in items:
            if _eval_spec_item(value, item):
                return ("red", "low")

    # crisis_high / critical_high
    for key in ("crisis_high", "critical_high"):
        ch = spec.get(key)
        if ch:
            items = ch if isinstance(ch, list) else [ch]
            for item in items:
                if _eval_spec_item(value, item):
                    return ("red", "high")

    # at_risk_low
    al = spec.get("at_risk_low")
    if al and isinstance(al, dict) and "min" in al and al["min"] <= value <= al.get("max", float("inf")):
        return ("yellow", "low")

    # at_risk_high
    ah = spec.get("at_risk_high")
    if ah and isinstance(ah, dict) and "min" in ah and ah["min"] <= value <= ah.get("max", float("inf")):
        return ("yellow", "high")

    return ("green", None)


def eval_vital_range(value: Optional[float], spec: dict) -> str:
    """Evaluate a single vital value against spec rules. Returns 'green', 'yellow', or 'red'."""
    level, _ = eval_vital_detail(value, spec)
    return level


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
        return ("error", True, ["Sensor dislodged or poor reading"])

    t = get_threshold_for_age(age)
    if not t:
        return ("green", False, [])

    reasons = []
    highest = "green"

    if spo2 is not None and "spo2_percent" in t:
        level, direction = eval_vital_detail(float(spo2), t["spo2_percent"])
        if level in ("red", "yellow"):
            prefix = "Critical Low" if level == "red" else "Low"
            reasons.append(f"{prefix} SpO2 ({int(spo2)}%)")
            if level == "red" or highest == "green":
                highest = level

    if hr is not None and "heart_rate_bpm" in t:
        level, direction = eval_vital_detail(float(hr), t["heart_rate_bpm"])
        if level in ("red", "yellow"):
            dir_str = "High" if direction == "high" else "Low"
            prefix = f"Critical {dir_str}" if level == "red" else dir_str
            reasons.append(f"{prefix} Heart Rate ({int(hr)} BPM)")
            if level == "red" or (level == "yellow" and highest != "red"):
                highest = level

    if temp_val is not None and "temperature" in t:
        temp_spec = t["temperature"].get("celsius", t["temperature"]) if isinstance(t["temperature"], dict) else t["temperature"]
        level, direction = eval_vital_detail(float(temp_val), temp_spec)
        if level in ("red", "yellow"):
            if direction == "high":
                prefix = "High Fever" if level == "red" else "High Temp"
            else:
                prefix = "Critical Low Temp" if level == "red" else "Low Temp"
            reasons.append(f"{prefix} ({float(temp_val):.1f}°C)")
            if level == "red" or (level == "yellow" and highest != "red"):
                highest = level

    sys_level, sys_dir = ("green", None)
    if sys_bp is not None and "sbp_mmHg" in t:
        sys_level, sys_dir = eval_vital_detail(float(sys_bp), t["sbp_mmHg"])

    dia_level, dia_dir = ("green", None)
    if dia_bp is not None and "dbp_mmHg" in t:
        dia_level, dia_dir = eval_vital_detail(float(dia_bp), t["dbp_mmHg"])

    if sys_level != "green" or dia_level != "green":
        bp_is_red = sys_level == "red" or dia_level == "red"
        bp_level = "red" if bp_is_red else "yellow"

        if sys_dir == "low" and dia_dir == "low":
            bp_prefix = "Critical Low BP" if bp_is_red else "Low BP"
        elif sys_dir == "high" and dia_dir == "high":
            bp_prefix = "Critical High BP" if bp_is_red else "High BP"
        elif sys_level != "green":
            dir_label = "High" if sys_dir == "high" else "Low"
            bp_prefix = f"Critical {dir_label} BP" if sys_level == "red" else f"{dir_label} BP"
        elif dia_level != "green":
            dir_label = "High" if dia_dir == "high" else "Low"
            bp_prefix = f"Critical {dir_label} BP" if dia_level == "red" else f"{dir_label} BP"
        else:
            bp_prefix = "Critical BP" if bp_is_red else "Abnormal BP"

        if sys_bp is not None and dia_bp is not None:
            bp_val_str = f"{int(sys_bp)}/{int(dia_bp)}"
        elif sys_bp is not None:
            bp_val_str = f"{int(sys_bp)}/-"
        else:
            bp_val_str = f"-/{int(dia_bp)}"

        reasons.append(f"{bp_prefix} ({bp_val_str} mmHg)")
        if bp_level == "red" or (bp_level == "yellow" and highest != "red"):
            highest = bp_level

    is_alert = highest in ("yellow", "red")
    return (highest, is_alert, reasons)


def compute_single_vital_trend(values: List[float]) -> str:
    """
    Evaluate pattern of consecutive vital readings in chronological order.
    Returns 'Stable Trend', 'Rising Trend', 'Falling Trend', or 'Fluctuating Trend'.
    """
    if not values or len(values) < 3:
        return "Insufficient Data"

    val_range = max(values) - min(values)
    if val_range <= 4.0:
        return "Stable Trend"

    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    increases = sum(1 for d in diffs if d > 1.0)
    decreases = sum(1 for d in diffs if d < -1.0)

    if increases >= 3 and decreases == 0:
        return "Rising Trend"
    if decreases >= 3 and increases == 0:
        return "Falling Trend"

    net_change = values[-1] - values[0]
    if net_change >= 10.0 and increases >= len(diffs) - 1:
        return "Rising Trend"
    if net_change <= -10.0 and decreases >= len(diffs) - 1:
        return "Falling Trend"

    return "Fluctuating Trend"


def analyze_blood_pressure_pattern(bp_records: list) -> dict:
    """
    Analyze the latest complete blood pressure records.
    `bp_records` are passed in newest-first or chronological order.
    Returns a dict with overall, sbp, dbp trends and count.
    """
    valid = [
        r for r in bp_records
        if getattr(r, "systolic_bp", None) is not None and getattr(r, "diastolic_bp", None) is not None
    ]

    latest_5 = valid[:5]
    if len(latest_5) < 3:
        return {
            "overall": "Insufficient Data",
            "sbp": "Insufficient Data",
            "dbp": "Insufficient Data",
            "count": len(latest_5)
        }

    chrono = list(reversed(latest_5))
    sbp_vals = [float(r.systolic_bp) for r in chrono]
    dbp_vals = [float(r.diastolic_bp) for r in chrono]

    sbp_trend = compute_single_vital_trend(sbp_vals)
    dbp_trend = compute_single_vital_trend(dbp_vals)

    if sbp_trend == dbp_trend:
        overall = sbp_trend
    elif sbp_trend == "Rising Trend" and dbp_trend == "Stable Trend":
        overall = "Rising Trend"
    elif dbp_trend == "Rising Trend" and sbp_trend == "Stable Trend":
        overall = "Rising Trend"
    elif sbp_trend == "Falling Trend" and dbp_trend == "Stable Trend":
        overall = "Falling Trend"
    elif dbp_trend == "Falling Trend" and sbp_trend == "Stable Trend":
        overall = "Falling Trend"
    elif sbp_trend == "Stable Trend" and dbp_trend == "Stable Trend":
        overall = "Stable Trend"
    else:
        overall = "Fluctuating Trend"

    return {
        "overall": overall,
        "sbp": sbp_trend,
        "dbp": dbp_trend,
        "count": len(latest_5)
    }

