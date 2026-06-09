# Virtuoso Flow Plugin

**Virtuoso Flow Plugin** is a Virtuoso-native workflow extension for analog and mixed-signal IC design. It embeds interactive panels, design-state viewers, proposal review dialogs, and simulation result dashboards directly inside Cadence Virtuoso, allowing designers to inspect, approve, and manage automated design actions without leaving the Virtuoso environment.

The plugin is designed to work together with **VFP Tunnel**, an external bridge service that connects Virtuoso to AI agents, command-line tools, simulation runners, and workflow automation scripts. While Virtuoso Flow Plugin handles the in-tool user interface, schematic/ADE interaction, and designer approval flow, VFP Tunnel manages agent communication, task scheduling, result parsing, artifact storage, constraint checking, and transaction history.

Unlike simple SKILL bridges that only expose remote command execution, this project focuses on **design-aware and auditable automation**. Every agent-assisted modification can be represented as a proposal, reviewed inside Virtuoso, applied as a transaction, linked to simulation results, and rolled back when necessary. The goal is to make AI-assisted IC design safer, more transparent, and more compatible with real analog design workflows.

## Key Features

* Virtuoso-native menu, dashboard, and review panels
* Current schematic, ADE, and simulation context extraction
* Agent proposal review and manual approval workflow
* Transaction-based schematic parameter modification
* ADE/Spectre task integration through VFP Tunnel
* Structured simulation metrics and constraint checking
* Artifact storage for logs, results, design context, and change history
* Designed for analog IC workflows such as OTA, op-amp, bias network, compensation, and switched-capacitor circuit optimization

## Architecture

The system is split into two cooperating components:

1. **Virtuoso Flow Plugin**
   A SKILL-based Virtuoso plugin responsible for in-Virtuoso UI rendering, current design context collection, schematic/ADE interaction, proposal visualization, and user-approved design updates.

2. **VFP Tunnel**
   An external bridge daemon responsible for AI-agent interfaces, JSON-RPC/MCP/CLI communication, task orchestration, simulation result parsing, constraint evaluation, logging, artifact management, and transaction persistence.

Together, they provide a controlled bridge between human designers, Virtuoso design data, simulation infrastructure, and AI-assisted automation tools.

## Repository Layout

```text
skill/      Virtuoso Flow Plugin — SKILL modules (the in-Virtuoso plugin)
tunnel/     VFP Tunnel — Python bridge daemon + `vfp` CLI (skeleton)
schemas/    Canonical data contract shared by both sides
examples/   Worked examples (e.g. RFC Class-AB op-amp fixtures)
scripts/    Convenience loaders / helpers
docs/       Project docs + bundled Cadence IC23.1 SKILL reference
tests/      Python tests for VFP Tunnel
project.md  Full project plan, milestones, and schemas
```

Both components live in one repository (monorepo); see
[`docs/development_notes.md`](docs/development_notes.md) for the rationale.

## Quick Start (Milestone 1 — plugin skeleton)

In the Virtuoso CIW:

```lisp
load("$PATH/Virtuoso-Flow-Plugin/scripts/load_vfp.il")
```

A **Virtuoso Flow** menu appears; `Open Dashboard` shows connection
status and the current library/cell/view. Full usage:
[`docs/plugin_usage.md`](docs/plugin_usage.md).

## Status

Milestone 1 (menu + dashboard + lib/cell/view) is implemented. VFP Tunnel
and the proposal / transaction / result milestones are scaffolded but not
yet implemented — see the status table in
[`docs/development_notes.md`](docs/development_notes.md).

## Thanks

[`Virtuoso CLI`](https://github.com/deanyou/virtuoso-cli): A full Rust rewrite and major extension of VBL.
[`Virtuoso-Bridge-Lite(VBL)`](https://github.com/Arcadia-1/virtuoso-bridge-lite): LLM Agents drive Cadence Virtuoso instances.
