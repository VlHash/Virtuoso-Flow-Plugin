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
