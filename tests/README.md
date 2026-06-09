# Tests

Python tests for VFP Tunnel (Milestone 2+). Planned suites mirror
`project.md` §7:

- `test_jsonrpc.py`
- `test_context_schema.py`
- `test_proposal_schema.py`
- `test_transaction.py`
- `test_constraints.py`
- `test_artifact_store.py`

Run from `tunnel/` once dependencies are installed:

```bash
cd tunnel
pip install -e .[dev]
pytest ../tests
```
