"""The JSON schemas are valid, the examples conform, and the optional
validator wires up to schemas/."""

import glob
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


def test_all_schemas_are_valid_draft202012():
    jsonschema = pytest.importorskip("jsonschema")
    files = glob.glob(os.path.join(ROOT, "schemas", "*.schema.json"))
    assert files, "no schema files found"
    for f in files:
        with open(f, encoding="utf-8") as fh:
            jsonschema.Draft202012Validator.check_schema(json.load(fh))


def test_validator_finds_schemas_dir():
    from vfp_tunnel.rpc import schemas as vfp_schemas
    assert (vfp_schemas.schemas_dir() / "context.schema.json").exists()
    assert vfp_schemas.load("context")["title"] == "VFP Design Context"


def test_example_context_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    assert vfp_schemas.validate(
        "context", _read("examples", "rfc_classab_opa", "sample_context.json")) is True


def test_example_proposal_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    assert vfp_schemas.validate(
        "proposal", _read("examples", "rfc_classab_opa", "sample_proposal.json")) is True


def test_example_result_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    assert vfp_schemas.validate(
        "result", _read("examples", "rfc_classab_opa", "sample_result.json")) is True


def test_bad_proposal_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {"schema_version": "0.1", "proposal_id": "p1", "status": "weird", "changes": []}
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("proposal", bad)


def test_context_with_connectivity_risks_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    ctx = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "connectivity_risks": [
            {"net": "net8", "kind": "auto_net", "terminals": ["M1.D", "M2.G"]},
            {"net": "net32", "kind": "auto_net", "terminals": ["R0.PLUS"]},
        ],
    }
    assert vfp_schemas.validate("context", ctx) is True


def test_context_bad_risk_kind_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "connectivity_risks": [{"net": "net8", "kind": "bogus"}],
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("context", bad)


def test_context_with_tb_lint_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    ctx = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "tb_lint": [
            {"kind": "floatingTerm", "subject": "R0.MINUS", "net": "net2"},
            {"kind": "danglingSource", "subject": "V0.PLUS", "net": None},
        ],
    }
    assert vfp_schemas.validate("context", ctx) is True


def test_context_bad_lint_kind_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "tb_lint": [{"kind": "nope", "subject": "X.Y"}],
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("context", bad)


def test_context_with_sim_preflight_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    ctx = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "sim_preflight": {
            "ready": False,
            "dirty": True,
            "cellview": "L/C/schematic",
            "fingerprint": "test=tran;conn=R0.MINUS=net2;params=R0.r=1K",
            "reason": "L/C/schematic has unsaved changes; save before netlisting",
        },
    }
    assert vfp_schemas.validate("context", ctx) is True


def test_context_with_layout_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    ctx = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "layout": {
            "cellview": {"lib": "L", "cell": "C", "view": "layout"},
            "bbox": [[0, 0], [12.5, 8.0]],
            "units": "um",
            "instances": [
                {"name": "M1", "master": "tsmcN65/nmos/layout",
                 "origin": [1.0, 1.0], "orient": "R0",
                 "bbox": [[1.0, 1.0], [2.0, 1.6]]}
            ],
            "layers": [{"layer": "M1", "purpose": "drawing", "shapes": 42}],
            "vias": 31,
        },
    }
    assert vfp_schemas.validate("context", ctx) is True


def test_context_bad_layout_bbox_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "layout": {"bbox": [[0, 0]]},  # bbox must be two points (LL, UR)
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("context", bad)


def test_context_bad_layout_layer_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "layout": {"layers": [{"purpose": "drawing"}]},  # missing required "layer"
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("context", bad)


def test_context_with_lvs_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    ctx = {
        "schema_version": "0.1",
        "cellview": {"lib": "Project", "cell": "inv", "view": "layout"},
        "lvs": {
            "schema_version": "0.1",
            "schematic": {"lib": "Project", "cell": "inv", "view": "schematic"},
            "layout": {"lib": "Project", "cell": "inv", "view": "layout"},
            "status": "issues",
            "devices": {
                "matched": 2,
                "only_in_layout": ["TAP0"],
                "only_in_schematic": [],
            },
            "net_mismatches": [
                {"inst_term": "M0.G",
                 "schematic_group": ["M0.G", "M1.G"],
                 "layout_group": ["M0.G"]},
            ],
        },
    }
    assert vfp_schemas.validate("context", ctx) is True


def test_context_clean_lvs_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    ctx = {
        "schema_version": "0.1",
        "cellview": {"lib": "Project", "cell": "inv", "view": "layout"},
        "lvs": {
            "schematic": {"lib": "Project", "cell": "inv", "view": "schematic"},
            "layout": {"lib": "Project", "cell": "inv", "view": "layout"},
            "status": "clean",
            "devices": {"matched": 2, "only_in_layout": [], "only_in_schematic": []},
            "net_mismatches": [],
        },
    }
    assert vfp_schemas.validate("context", ctx) is True


def test_context_bad_lvs_status_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "layout"},
        "lvs": {"status": "maybe"},  # status must be clean|issues
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("context", bad)


def test_context_lvs_missing_status_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1",
        "cellview": {"lib": "L", "cell": "C", "view": "layout"},
        "lvs": {"devices": {"matched": 0}},  # missing required "status"
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("context", bad)


def test_transaction_with_checkpoint_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    txn = {
        "schema_version": "0.1",
        "transaction_id": "t_abc123",
        "status": "applied",
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "before": [],
        "after": [],
        "checkpoint": {
            "view": "schematic_vfpckpt_preapply_Jun_13_11_04_26_2026",
            "created_at": "2026-06-13T11:04:26",
        },
    }
    assert vfp_schemas.validate("transaction", txn) is True


def test_transaction_layout_geom_conforms():
    pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    txn = {
        "schema_version": "0.1",
        "transaction_id": "t_lay",
        "status": "applied",
        "kind": "layout_geom",
        "cellview": {"lib": "Project", "cell": "inv", "view": "layout"},
        "geometry": {
            "before_counts": {"shapes": 40, "vias": 6, "instances": 2},
            "after_counts": {"shapes": 41, "vias": 6, "instances": 2},
            "changes": [
                {"kind": "shapeAdded", "subject": "M2", "detail": "added rect on M2"},
                {"kind": "instMoved", "subject": "M1", "detail": "M1 moved"},
            ],
        },
        "checkpoint": {
            "view": "layout_vfpckpt_edit_Jun_22_15_00_00_2026",
            "created_at": "2026-06-22T15:00:00",
        },
    }
    assert vfp_schemas.validate("transaction", txn) is True


def test_transaction_bad_kind_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1", "transaction_id": "t", "status": "applied",
        "kind": "bogus_kind",
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("transaction", bad)


def test_transaction_bad_geometry_change_kind_raises():
    jsonschema = pytest.importorskip("jsonschema")
    from vfp_tunnel.rpc import schemas as vfp_schemas
    bad = {
        "schema_version": "0.1", "transaction_id": "t", "status": "applied",
        "kind": "layout_geom",
        "geometry": {"changes": [{"kind": "shapeWiggled", "subject": "M2"}]},
    }
    with pytest.raises(jsonschema.ValidationError):
        vfp_schemas.validate("transaction", bad)
