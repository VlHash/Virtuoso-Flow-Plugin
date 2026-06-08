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
