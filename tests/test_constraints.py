def test_all_pass():
    from vfp_tunnel.constraints.engine import check
    res = check({"A0_dB": 102, "PM_deg": 70},
                {"A0_dB": {"min": 100}, "PM_deg": {"min": 65, "max": 80}})
    assert res["overall"] == "pass"
    assert all(i["status"] == "pass" for i in res["items"])


def test_fail_below_min():
    from vfp_tunnel.constraints.engine import check
    res = check({"A0_dB": 90}, {"A0_dB": {"min": 100}})
    assert res["overall"] == "fail"
    assert res["items"][0]["status"] == "fail"
    assert "min" in res["items"][0]["reason"]


def test_fail_above_max():
    from vfp_tunnel.constraints.engine import check
    res = check({"PM_deg": 85}, {"PM_deg": {"min": 65, "max": 80}})
    assert res["overall"] == "fail"
    assert "max" in res["items"][0]["reason"]


def test_missing_metric_is_fail():
    from vfp_tunnel.constraints.engine import check
    res = check({}, {"UGB_MHz": {"min": 50}})
    assert res["overall"] == "fail"
    assert res["items"][0]["reason"] == "not reported"


def test_items_sorted_and_value_carried():
    from vfp_tunnel.constraints.engine import check
    res = check({"b": 2, "a": 1}, {"b": {"max": 5}, "a": {"min": 0}})
    assert [i["metric"] for i in res["items"]] == ["a", "b"]
    assert res["items"][0]["value"] == 1


def test_empty_limits_pass():
    from vfp_tunnel.constraints.engine import check
    assert check({"x": 1}, {})["overall"] == "pass"
