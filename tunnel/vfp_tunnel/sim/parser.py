import json


def _parse_text(text):
    metrics = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        for sep in ("=", ",", "\t", " "):
            if sep in line:
                key, _, val = line.partition(sep)
                key = key.strip()
                val = val.strip()
                try:
                    metrics[key] = float(val)
                except ValueError:
                    pass
                break
    return metrics


def parse_result_file(path):
    """Read a metrics/result file into result blocks: ``metrics`` (always) plus
    ``provenance`` / ``metric_quality`` when the file is a JSON result object
    (schema 0.2). A line-based text file (``name=value`` / ``name,value`` /
    ``name value``) yields metrics only.
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        obj = json.loads(text)
        from .metrics import extract_metrics
        out = {"metrics": extract_metrics(obj)}
        if isinstance(obj, dict):
            for key in ("provenance", "metric_quality"):
                block = obj.get(key)
                if isinstance(block, dict) and block:
                    out[key] = block
        return out
    return {"metrics": _parse_text(text)}


def parse_metrics_file(path):
    """Back-compat shim: just the ``metrics`` dict (see ``parse_result_file``)."""
    return parse_result_file(path)["metrics"]
