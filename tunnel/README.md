# VFP Tunnel

External bridge daemon for the [Virtuoso Flow Plugin](../README.md). It
exposes a localhost JSON-RPC API (default `127.0.0.1:47891`) and a `vfp`
CLI to AI agents and scripts, and manages sessions, proposals,
transactions, simulation results, constraints, and artifacts.

> Skeleton only (Milestone 2 not yet started). The package currently
> provides the project layout and a placeholder CLI.

## Install (editable, for development)

```bash
cd tunnel
pip install -e .[dev]
```

## Layout

```
vfp_tunnel/
  cli.py daemon.py config.py logging_config.py
  rpc/ session/ design/ proposal/ transaction/
  sim/ constraints/ artifact/ agent/
```

See [`../project.md`](../project.md) §9 for the planned CLI commands and
JSON-RPC method set, and [`../schemas/`](../schemas) for the data contract.
