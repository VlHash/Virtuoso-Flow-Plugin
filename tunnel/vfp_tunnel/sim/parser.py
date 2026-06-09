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


def parse_metrics_file(path):
    """Read a metrics/result file into a {name: number} dict.

    Supports JSON (a result object or a flat name->number map) and a simple
    line-based text format (``name=value`` / ``name,value`` / ``name value``).
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        obj = json.loads(text)
        from .metrics import extract_metrics
        return extract_metrics(obj)
    return _parse_text(text)
