import time
import uuid


def _coerce_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_metrics(obj):
    """Pull a {name: number} metrics dict out of a parsed structure.

    Accepts either a full result object (with a ``metrics`` key) or a flat
    mapping of name -> number. Non-numeric entries are dropped.
    """
    src = obj.get("metrics") if isinstance(obj, dict) and "metrics" in obj else obj
    out = {}
    if isinstance(src, dict):
        for k, v in src.items():
            n = _coerce_number(v)
            if n is not None:
                out[str(k)] = n
    return out


def make_result(data):
    """Normalise an incoming result dict; assign id/version/source if absent."""
    r = dict(data) if isinstance(data, dict) else {}
    if not r.get("result_id"):
        r["result_id"] = "r_" + uuid.uuid4().hex[:12]
    r.setdefault("schema_version", "0.1")
    r.setdefault("source", "manual")
    r["metrics"] = extract_metrics(r)
    r.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return r
