def _evaluate_one(metric, value, spec):
    if value is None:
        return {"metric": metric, "status": "fail", "reason": "not reported"}
    lo = spec.get("min")
    hi = spec.get("max")
    item = {"metric": metric, "value": value, "status": "pass"}
    if lo is not None and value < lo:
        item["status"] = "fail"
        item["reason"] = "%s < min %s" % (value, lo)
    elif hi is not None and value > hi:
        item["status"] = "fail"
        item["reason"] = "%s > max %s" % (value, hi)
    return item


def check(metrics, limits):
    """Evaluate result *metrics* against constraint *limits*.

    *metrics* maps metric name -> number; *limits* maps metric name ->
    {min?, max?}. Returns {"overall": "pass"|"fail", "items": [...]}.
    """
    metrics = metrics or {}
    items = []
    for metric in sorted(limits or {}):
        spec = limits[metric] or {}
        items.append(_evaluate_one(metric, metrics.get(metric), spec))
    overall = "pass" if all(i["status"] == "pass" for i in items) else "fail"
    return {"overall": overall, "items": items}
