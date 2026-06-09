# Virtuoso Flow Plugin Project Plan

## 1. Project Overview

**Virtuoso Flow Plugin** is a Virtuoso-native workflow extension for analog and mixed-signal IC design. It provides an embedded user interface inside Cadence Virtuoso for design-state visualization, agent proposal review, simulation result display, transaction-based schematic modification, and workflow control.

The system is divided into two cooperating components:

1. **Virtuoso Flow Plugin**
   The internal Virtuoso-side plugin implemented mainly in SKILL. It is responsible for UI rendering, menu integration, schematic/ADE interaction, current design context extraction, proposal visualization, user approval, and controlled design modification.

2. **VFP Tunnel**
   The external bridge daemon responsible for AI-agent interaction, CLI/MCP/JSON-RPC APIs, task orchestration, simulation result parsing, artifact storage, constraint checking, logging, and transaction history.

The key design principle is:

> Virtuoso Flow Plugin handles what must be visible and executable inside Virtuoso.
> VFP Tunnel handles what should be managed outside Virtuoso.

This project must not become a simple remote SKILL executor. The goal is to build a design-aware, auditable, and user-approved automation workflow for analog IC design.

---

## 2. Core Objectives

### 2.1 Primary Goals

* Provide a Virtuoso-native plugin that can be loaded directly inside Cadence Virtuoso.
* Add an internal menu and dashboard panel inside Virtuoso.
* Extract current schematic, instance, parameter, net, and ADE context.
* Allow external agents to submit design modification proposals.
* Display agent proposals inside Virtuoso for user review.
* Apply approved changes as transactions.
* Support rollback of previous parameter modifications.
* Connect with external VFP Tunnel for agent interface and workflow orchestration.
* Display simulation metrics and constraint checking results inside Virtuoso.
* Keep all agent-assisted actions auditable and reversible.

### 2.2 Non-Goals for MVP

The first version should not attempt to implement:

* Automatic layout generation.
* DRC/LVS/PEX automation.
* Full Maestro GUI replacement.
* Arbitrary topology synthesis.
* Full gm/ID design automation.
* Full waveform viewer replacement.
* Unrestricted remote SKILL execution.

These can be considered after the core plugin workflow is stable.

---

## 3. Target User Workflow

The expected workflow is:

1. User opens a schematic or ADE session in Cadence Virtuoso.
2. User loads Virtuoso Flow Plugin.
3. The plugin adds an `AnalogFlow` or `Virtuoso Flow` menu to Virtuoso.
4. User opens the embedded dashboard.
5. Plugin connects to VFP Tunnel running externally.
6. Plugin exports current design context to VFP Tunnel.
7. External Agent reads the design context through VFP Tunnel.
8. Agent creates a structured proposal, for example:

   * modify capacitor value;
   * modify resistor value;
   * modify MOS parameter;
   * run an ADE test;
   * check constraints.
9. Virtuoso Flow Plugin displays the proposal inside Virtuoso.
10. User approves, rejects, or edits the proposal.
11. Approved changes are applied by the Virtuoso plugin.
12. A transaction record is saved.
13. VFP Tunnel runs or triggers simulation.
14. Simulation results are parsed and sent back.
15. Virtuoso dashboard displays metrics and pass/fail status.
16. User continues iteration or rolls back.

---

## 4. System Architecture

```text
┌───────────────────────────────────────────────┐
│              Cadence Virtuoso                 │
│                                               │
│  ┌─────────────────────────────────────────┐  │
│  │          Virtuoso Flow Plugin            │  │
│  │                                         │  │
│  │  SKILL Menu / Dashboard / Forms         │  │
│  │  Schematic Context / ADE Context        │  │
│  │  Proposal Review / User Approval        │  │
│  │  Transaction Apply / Rollback           │  │
│  └───────────────────┬─────────────────────┘  │
└──────────────────────┼────────────────────────┘
                       │
                       │ JSON-RPC / Local Socket
                       │
┌──────────────────────▼────────────────────────┐
│                  VFP Tunnel                   │
│                                                │
│  Session Manager                              │
│  Agent API / CLI / MCP Interface              │
│  Proposal Manager                             │
│  Task Queue                                   │
│  Simulation Manager                           │
│  Result Parser                                │
│  Constraint Engine                            │
│  Artifact Store                               │
│  Transaction Store                            │
└──────────────────────┬────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
┌───────▼────────┐           ┌────────▼────────┐
│ AI Agent       │           │ CLI / Scripts   │
│ Claude/Codex   │           │ vfp command     │
└────────────────┘           └─────────────────┘
```

---

## 5. Component Responsibilities

## 5.1 Virtuoso Flow Plugin

The internal Virtuoso plugin is responsible for:

* Loading into Virtuoso through SKILL.
* Registering plugin menu entries.
* Rendering internal UI panels using Virtuoso UI forms.
* Detecting current library/cell/view.
* Reading schematic instance data.
* Reading instance parameters.
* Reading schematic net connectivity.
* Reading basic ADE context if available.
* Sending design context to VFP Tunnel.
* Receiving pending proposals from VFP Tunnel.
* Displaying proposals for user approval.
* Applying approved schematic parameter changes.
* Recording before/after change information.
* Triggering rollback when requested.
* Displaying latest metrics, constraints, and task status.

The internal plugin should not:

* Directly talk to AI models.
* Parse large simulation data.
* Store large artifact history.
* Run complex optimization logic.
* Expose unrestricted SKILL evaluation to agents.

---

## 5.2 VFP Tunnel

The external daemon is responsible for:

* Maintaining connection with Virtuoso Flow Plugin.
* Providing CLI/API/MCP interface to agents.
* Receiving current design context from Virtuoso.
* Managing agent-generated proposals.
* Managing task queue and task status.
* Running or triggering ADE/Spectre tasks.
* Parsing simulation outputs.
* Checking design constraints.
* Saving artifacts, logs, metrics, and transactions.
* Returning structured results to Virtuoso Flow Plugin.
* Enforcing permission and safety policies.

The external daemon should not:

* Modify Virtuoso design data without user approval.
* Depend on GUI clicking automation.
* Treat Virtuoso as a black-box screen target.
* Allow agents to execute arbitrary destructive SKILL code by default.

---

## 6. MVP Scope

The MVP should implement a complete but narrow loop:

> Read current schematic context → submit proposal → review inside Virtuoso → approve change → apply transaction → run or trigger simulation → parse metrics → display pass/fail result → rollback if needed.

### 6.1 MVP Required Features

#### Virtuoso Flow Plugin

* Loadable SKILL plugin.
* Menu entry inside Virtuoso.
* Dashboard form.
* Connection status display.
* Current library/cell/view display.
* Current instance list extraction.
* Instance parameter read.
* Instance parameter update.
* Design context export.
* Proposal display panel.
* Approve/reject proposal buttons.
* Transaction snapshot before modification.
* Rollback last transaction.
* Latest result display.

#### VFP Tunnel

* Local daemon.
* JSON-RPC server.
* CLI entrypoint.
* Session registration.
* Design context storage.
* Proposal creation API.
* Proposal status management.
* Transaction database or file store.
* Constraint checking from YAML.
* Simulation metrics ingestion.
* Latest result API.
* Artifact directory management.

### 6.2 MVP Optional Features

* ADE test triggering.
* Spectre standalone task execution.
* Basic PSF/log parser.
* MCP server.
* Dashboard auto-refresh.
* Multiple Virtuoso sessions.

### 6.3 Deferred Features

* Layout support.
* DRC/LVS/PEX support.
* Waveform plotting inside Virtuoso.
* Multi-user collaboration.
* Full agent optimization loop.
* Remote SSH session support.
* Rust-based daemon rewrite.

---

## 7. Proposed Repository Structure

```text
virtuoso-flow-plugin/
├── README.md
├── LICENSE
├── docs/
│   ├── architecture.md
│   ├── plugin_usage.md
│   ├── vfp_tunnel_api.md
│   ├── proposal_schema.md
│   ├── transaction_schema.md
│   ├── constraint_schema.md
│   └── development_notes.md
│
├── skill/
│   ├── vfp_init.il
│   ├── vfp_menu.il
│   ├── vfp_dashboard.il
│   ├── vfp_rpc_client.il
│   ├── vfp_rpc_server.il
│   ├── vfp_context.il
│   ├── vfp_schematic.il
│   ├── vfp_ade.il
│   ├── vfp_proposal.il
│   ├── vfp_transaction.il
│   └── vfp_utils.il
│
├── tunnel/
│   ├── pyproject.toml
│   ├── vfp_tunnel/
│   │   ├── __init__.py
│   │   ├── cli.py
│   │   ├── daemon.py
│   │   ├── config.py
│   │   ├── logging_config.py
│   │   │
│   │   ├── rpc/
│   │   │   ├── jsonrpc.py
│   │   │   ├── transport.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── session/
│   │   │   ├── manager.py
│   │   │   └── registry.py
│   │   │
│   │   ├── design/
│   │   │   ├── context.py
│   │   │   ├── schematic.py
│   │   │   └── ade.py
│   │   │
│   │   ├── proposal/
│   │   │   ├── manager.py
│   │   │   ├── model.py
│   │   │   └── policy.py
│   │   │
│   │   ├── transaction/
│   │   │   ├── manager.py
│   │   │   ├── model.py
│   │   │   └── rollback.py
│   │   │
│   │   ├── sim/
│   │   │   ├── manager.py
│   │   │   ├── parser.py
│   │   │   └── metrics.py
│   │   │
│   │   ├── constraints/
│   │   │   ├── engine.py
│   │   │   └── schema.py
│   │   │
│   │   ├── artifact/
│   │   │   ├── store.py
│   │   │   └── paths.py
│   │   │
│   │   └── agent/
│   │       ├── tools.py
│   │       └── mcp_server.py
│   │
├── examples/
│   ├── folded_cascode_opa/
│   │   ├── constraints.yaml
│   │   ├── sample_context.json
│   │   ├── sample_proposal.json
│   │   └── README.md
│   │
│   └── rfc_classab_opa/
│       ├── constraints.yaml
│       ├── sample_context.json
│       ├── sample_proposal.json
│       └── README.md
│
├── scripts/
│   ├── install_skill.sh
│   ├── start_tunnel.sh
│   ├── stop_tunnel.sh
│   └── collect_logs.sh
│
└── tests/
    ├── test_jsonrpc.py
    ├── test_context_schema.py
    ├── test_proposal_schema.py
    ├── test_transaction.py
    ├── test_constraints.py
    └── test_artifact_store.py
```

---

## 8. Virtuoso Plugin Module Plan

### 8.1 `vfp_init.il`

Purpose:

* Load all SKILL modules.
* Initialize plugin state.
* Register menu.
* Initialize RPC connection state.

Required functions:

```lisp
vfpLoad()
vfpInit()
vfpUnload()
vfpGetVersion()
```

Expected behavior:

* User can load the plugin by calling:

```lisp
load("skill/vfp_init.il")
vfpInit()
```

---

### 8.2 `vfp_menu.il`

Purpose:

* Add menu entries to Virtuoso.

Menu structure:

```text
Virtuoso Flow
├── Connect VFP Tunnel
├── Open Dashboard
├── Export Current Context
├── Show Pending Proposals
├── Apply Approved Proposal
├── Rollback Last Transaction
├── Run Selected ADE Test
├── Refresh Results
└── Settings
```

Required functions:

```lisp
vfpRegisterMenu()
vfpUnregisterMenu()
```

---

### 8.3 `vfp_dashboard.il`

Purpose:

* Render the main dashboard form inside Virtuoso.

Dashboard fields:

* VFP Tunnel connection status.
* Current library/cell/view.
* Current ADE test name.
* Last simulation metrics.
* Constraint status.
* Pending proposal summary.
* Latest transaction ID.
* Buttons:

  * Connect
  * Export Context
  * Refresh
  * Approve
  * Reject
  * Rollback
  * Run Test

Required functions:

```lisp
vfpOpenDashboard()
vfpUpdateDashboard()
vfpCloseDashboard()
```

---

### 8.4 `vfp_context.il`

Purpose:

* Extract current design context.

Required extracted fields:

```json
{
  "cellview": {
    "lib": "...",
    "cell": "...",
    "view": "schematic"
  },
  "instances": [],
  "nets": [],
  "ports": [],
  "ade": {},
  "timestamp": "..."
}
```

Required functions:

```lisp
vfpGetCurrentCellView()
vfpExtractInstances(cv)
vfpExtractNets(cv)
vfpExtractPorts(cv)
vfpExtractDesignContext()
vfpExportDesignContext()
```

---

### 8.5 `vfp_schematic.il`

Purpose:

* Provide controlled schematic access.

Required functions:

```lisp
vfpListInstances(cv)
vfpGetInstanceParams(cv instName)
vfpSetInstanceParam(cv instName paramName value)
vfpBatchSetInstanceParams(cv changes)
vfpSaveCellView(cv)
```

Important rule:

* All parameter changes must be performed through transaction-aware wrapper functions.
* Do not expose unrestricted raw SKILL execution through the agent-facing API.

---

### 8.6 `vfp_proposal.il`

Purpose:

* Receive, display, and handle proposals.

Proposal states:

```text
pending
approved
rejected
applied
failed
rolled_back
```

Required functions:

```lisp
vfpFetchPendingProposals()
vfpShowProposal(proposal)
vfpApproveProposal(proposalId)
vfpRejectProposal(proposalId)
vfpApplyProposal(proposalId)
```

---

### 8.7 `vfp_transaction.il`

Purpose:

* Save before/after snapshots for design modifications.
* Support rollback.

Required functions:

```lisp
vfpCreateTransaction(proposalId changes)
vfpRecordBeforeState(changes)
vfpRecordAfterState(changes)
vfpApplyTransaction(transactionId)
vfpRollbackTransaction(transactionId)
vfpGetLastTransaction()
```

Transaction record should contain:

```json
{
  "transaction_id": "...",
  "proposal_id": "...",
  "cellview": "...",
  "changes": [],
  "before": [],
  "after": [],
  "timestamp": "...",
  "status": "applied"
}
```

---

### 8.8 `vfp_ade.il`

Purpose:

* Provide minimal ADE interaction.

MVP functions:

```lisp
vfpGetAdeContext()
vfpListAdeTests()
vfpGetActiveAdeTest()
vfpRunAdeTest(testName)
```

If ADE automation becomes unstable, the MVP may allow VFP Tunnel to only ingest result files first. Direct ADE automation can be implemented as a second-stage feature.

---

### 8.9 `vfp_rpc_client.il`

Purpose:

* Communicate with VFP Tunnel.

Required RPC methods:

```text
session.register
session.ping
design.context.update
proposal.list
proposal.approve
proposal.reject
transaction.record
transaction.rollback
result.latest
task.status
```

---

## 9. VFP Tunnel Module Plan

### 9.1 CLI

Command name:

```bash
vfp
```

Required commands:

```bash
vfp tunnel start
vfp tunnel stop
vfp tunnel status

vfp session list
vfp session current

vfp context show
vfp context export

vfp proposal create --file proposal.json
vfp proposal list
vfp proposal show <proposal_id>
vfp proposal approve <proposal_id>
vfp proposal reject <proposal_id>

vfp transaction list
vfp transaction show <transaction_id>
vfp transaction rollback <transaction_id>

vfp result latest
vfp constraint check --file constraints.yaml
```

---

### 9.2 JSON-RPC API

Minimum methods:

```text
session.register
session.ping
session.status

design.context.update
design.context.get

proposal.create
proposal.list
proposal.get
proposal.approve
proposal.reject
proposal.mark_applied
proposal.mark_failed

transaction.create
transaction.list
transaction.get
transaction.rollback
transaction.mark_rolled_back

result.update
result.latest

constraint.check

task.create
task.status
task.cancel
```

---

## 10. Data Schemas

### 10.1 Design Context Schema

```json
{
  "schema_version": "0.1",
  "source": "virtuoso-flow-plugin",
  "timestamp": "2026-06-09T00:00:00",
  "cellview": {
    "lib": "RFCOPA",
    "cell": "XOPA",
    "view": "schematic"
  },
  "instances": [
    {
      "name": "M3",
      "master": {
        "lib": "tsmcN65",
        "cell": "pmos",
        "view": "symbol"
      },
      "params": {
        "w": "1u",
        "l": "120n",
        "m": "4",
        "nf": "2"
      },
      "nets": {
        "G": "Vbin",
        "D": "net_tail",
        "S": "VDD",
        "B": "VDD"
      }
    }
  ],
  "ports": [],
  "nets": [],
  "ade": {
    "available": true,
    "active_test": "openloop_stb",
    "tests": ["dcop", "openloop_stb", "tran_sc"]
  },
  "last_result": {
    "available": false
  }
}
```

---

### 10.2 Proposal Schema

```json
{
  "schema_version": "0.1",
  "proposal_id": "p_20260609_001",
  "created_by": "agent",
  "status": "pending",
  "cellview": {
    "lib": "RFCOPA",
    "cell": "XOPA",
    "view": "schematic"
  },
  "reason": "Phase margin is too high. Reduce Miller compensation capacitance to increase bandwidth and lower excessive stability margin.",
  "changes": [
    {
      "type": "set_instance_param",
      "instance": "C0",
      "param": "c",
      "before": "12f",
      "after": "6f"
    },
    {
      "type": "set_instance_param",
      "instance": "RZC0",
      "param": "r",
      "before": "10k",
      "after": "4.7k"
    }
  ],
  "expected_effect": {
    "PM": "decrease",
    "UGB": "increase",
    "risk": "May reduce stability margin too much if compensation is reduced aggressively."
  },
  "requires_user_approval": true
}
```

---

### 10.3 Transaction Schema

```json
{
  "schema_version": "0.1",
  "transaction_id": "tx_20260609_001",
  "proposal_id": "p_20260609_001",
  "status": "applied",
  "cellview": {
    "lib": "RFCOPA",
    "cell": "XOPA",
    "view": "schematic"
  },
  "before": [
    {
      "instance": "C0",
      "param": "c",
      "value": "12f"
    }
  ],
  "after": [
    {
      "instance": "C0",
      "param": "c",
      "value": "6f"
    }
  ],
  "timestamp": "2026-06-09T00:00:00",
  "linked_results": []
}
```

---

### 10.4 Result Schema

```json
{
  "schema_version": "0.1",
  "result_id": "res_20260609_001",
  "source": "spectre_or_ade",
  "cellview": {
    "lib": "RFCOPA",
    "cell": "XOPA",
    "view": "schematic"
  },
  "test": "openloop_stb",
  "metrics": {
    "A0_dB": 115.75,
    "UGB_MHz": 65.87,
    "PM_deg": 136.73,
    "power_mW": 1.25
  },
  "constraints": {
    "overall": "fail",
    "items": [
      {
        "metric": "A0_dB",
        "value": 115.75,
        "status": "pass"
      },
      {
        "metric": "PM_deg",
        "value": 136.73,
        "status": "fail",
        "reason": "above maximum 80 deg"
      }
    ]
  },
  "artifacts": {
    "log": "runs/res_20260609_001/spectre.out",
    "metrics": "runs/res_20260609_001/metrics.json"
  }
}
```

---

### 10.5 Constraint File Schema

```yaml
schema_version: 0.1

design:
  lib: RFCOPA
  cell: XOPA
  view: schematic

metrics:
  A0_dB:
    min: 100
  UGB_MHz:
    min: 50
    max: 100
  PM_deg:
    min: 65
    max: 80
  Itotal_uA:
    max: 600
  Itail_uA:
    min: 120
  stage2_ratio:
    max: 0.6

dcop:
  require_saturation:
    devices:
      - M0
      - M1
      - M2
      - M3
      - M6
      - M7
      - M9
      - M10
      - M11
      - M12
  min_sat_margin_mV: 30

permissions:
  allow_modify:
    - "M*.w"
    - "M*.l"
    - "M*.m"
    - "C*.c"
    - "R*.r"
  deny_modify:
    - "VDD.*"
    - "VSS.*"
    - "model.*"
```

---

## 11. Safety and Permission Rules

The plugin and tunnel must enforce the following rules:

1. Agent proposals must be reviewed before modifying the schematic.
2. No unrestricted `evalstring` API should be exposed to external agents in MVP.
3. All modifications must be recorded as transactions.
4. Rollback must be available for parameter changes.
5. Each proposal must include reason, changes, and expected effect.
6. Each applied proposal must be linked to a transaction ID.
7. Each simulation result should be linked to the input context and transaction when available.
8. Any failed operation must return a structured error.
9. Destructive operations must require explicit user approval.
10. The plugin must verify current lib/cell/view before applying changes.

---

## 12. Development Milestones

## Milestone 1: Virtuoso Plugin Skeleton

Deliverables:

* `vfp_init.il`
* `vfp_menu.il`
* `vfp_dashboard.il`
* Basic menu registration
* Basic dashboard display
* Current lib/cell/view display

Acceptance tests:

* User can load the plugin inside Virtuoso.
* A menu named `Virtuoso Flow` or `AnalogFlow` appears.
* User can open the dashboard.
* Dashboard displays current design context at least as lib/cell/view.

---

## Milestone 2: VFP Tunnel Skeleton

Deliverables:

* Python package structure.
* CLI command `vfp`.
* JSON-RPC server.
* Session registration API.
* Tunnel status API.

Acceptance tests:

```bash
vfp tunnel start
vfp tunnel status
vfp session list
```

Virtuoso plugin should be able to ping VFP Tunnel.

---

## Milestone 3: Design Context Export

Deliverables:

* Instance extraction from current schematic.
* Parameter extraction.
* Net/terminal mapping extraction.
* Design context JSON generation.
* Send context to VFP Tunnel.

Acceptance tests:

* User opens a schematic.
* User clicks `Export Current Context`.
* VFP Tunnel receives and stores context.
* `vfp context show` displays the latest context.

---

## Milestone 4: Proposal Workflow

Deliverables:

* Proposal schema.
* Proposal creation from CLI or agent API.
* Proposal list API.
* Proposal display in Virtuoso dashboard.
* Approve/reject UI buttons.

Acceptance tests:

```bash
vfp proposal create --file examples/rfc_classab_opa/sample_proposal.json
vfp proposal list
```

Virtuoso dashboard should show the pending proposal.

---

## Milestone 5: Transactional Parameter Modification

Deliverables:

* Transaction schema.
* Before-state capture.
* Parameter modification in schematic.
* After-state capture.
* Transaction storage.
* Rollback last transaction.

Acceptance tests:

* Create proposal to modify one capacitor value.
* Approve proposal inside Virtuoso.
* Verify schematic parameter changes.
* Verify transaction record is saved.
* Rollback restores original parameter value.

---

## Milestone 6: Result and Constraint Display

Deliverables:

* Result schema.
* Manual result ingestion API.
* Constraint YAML parser.
* Constraint checking engine.
* Dashboard result display.

Acceptance tests:

```bash
vfp result latest
vfp constraint check --file examples/rfc_classab_opa/constraints.yaml
```

Virtuoso dashboard should display pass/fail status for key metrics.

---

## Milestone 7: ADE/Spectre Integration

Deliverables:

* Basic ADE test listing.
* Basic ADE test trigger if feasible.
* Simulation task status.
* Result parsing hook.
* Artifact folder per run.

Acceptance tests:

* Run selected ADE test or ingest an existing result.
* Parse metrics into `result.json`.
* Display latest metrics in Virtuoso dashboard.

---

## 13. Example MVP Demo

Use a two-stage op-amp or RFC Class-AB op-amp schematic.

Demo flow:

1. Open `RFCOPA/XOPA/schematic`.
2. Load plugin:

```lisp
load("skill/vfp_init.il")
vfpInit()
```

3. Start tunnel:

```bash
vfp tunnel start
```

4. Connect plugin to tunnel.
5. Export current context.
6. Create proposal:

```bash
vfp proposal create --file examples/rfc_classab_opa/sample_proposal.json
```

7. Show proposal in Virtuoso.
8. Approve proposal.
9. Schematic parameter is modified.
10. Transaction is saved.
11. Ingest or run simulation result.
12. Dashboard shows metrics:

    * A0
    * UGB
    * PM
    * power
    * pass/fail
13. Roll back transaction if needed.

---

## 14. Engineering Notes

### 14.1 SKILL UI

Use standard Virtuoso SKILL UI APIs first. Avoid complicated custom rendering in MVP.

Preferred UI elements:

* Pulldown menu.
* App form.
* Text fields.
* Report fields.
* Buttons.
* Status labels.

The first dashboard can be simple. Functionality is more important than UI complexity.

---

### 14.2 Communication

Use localhost JSON-RPC for MVP.

Recommended default endpoint:

```text
127.0.0.1:47891
```

All messages should include:

```json
{
  "jsonrpc": "2.0",
  "id": "...",
  "method": "...",
  "params": {}
}
```

Responses should follow:

```json
{
  "jsonrpc": "2.0",
  "id": "...",
  "result": {}
}
```

Errors should follow:

```json
{
  "jsonrpc": "2.0",
  "id": "...",
  "error": {
    "code": -32000,
    "message": "Error description",
    "data": {}
  }
}
```

---

### 14.3 Artifact Storage

Default artifact directory:

```text
.vfp/
├── sessions/
├── contexts/
├── proposals/
├── transactions/
├── results/
├── runs/
└── logs/
```

Each run should store:

```text
runs/<run_id>/
├── context.json
├── proposal.json
├── transaction.json
├── result.json
├── constraints.yaml
├── logs/
└── artifacts/
```

---

### 14.4 Logging

Both plugin and tunnel should log.

Tunnel logs:

```text
.vfp/logs/vfp_tunnel.log
```

Plugin logs:

```text
CIW output and optional .vfp/logs/vfp_plugin.log
```

Log important events:

* plugin loaded
* tunnel connected
* context exported
* proposal received
* proposal approved/rejected
* transaction applied
* rollback executed
* result updated
* constraint check completed
* error occurred

---

## 15. Suggested Implementation Order

Implement in this exact order:

1. Create repository structure.
2. Implement SKILL plugin loading.
3. Implement Virtuoso menu.
4. Implement dashboard skeleton.
5. Implement Python VFP Tunnel skeleton.
6. Implement JSON-RPC ping.
7. Connect plugin to tunnel.
8. Extract current lib/cell/view.
9. Extract instance list.
10. Extract instance parameters.
11. Export context to tunnel.
12. Implement proposal schema and storage.
13. Implement proposal creation CLI.
14. Display pending proposal in Virtuoso.
15. Implement approve/reject.
16. Implement parameter modification.
17. Add transaction before/after snapshot.
18. Implement rollback.
19. Implement result ingestion.
20. Implement constraint checking.
21. Display result and constraint status in dashboard.
22. Add ADE/Spectre automation after the above is stable.

---

## 16. Initial Agent Task List

The development Agent should begin with the following concrete tasks:

### Task 1: Create Project Skeleton

Create the repository structure exactly as described in Section 7.

### Task 2: Implement SKILL Loader

Create:

```text
skill/vfp_init.il
skill/vfp_menu.il
skill/vfp_dashboard.il
skill/vfp_utils.il
```

The user should be able to run:

```lisp
load("skill/vfp_init.il")
vfpInit()
```

Expected result:

* Plugin initializes without error.
* Menu entry appears.
* Dashboard can open.

### Task 3: Implement VFP Tunnel CLI Skeleton

Create Python package under `tunnel/`.

Expected commands:

```bash
vfp tunnel start
vfp tunnel status
```

### Task 4: Implement JSON-RPC Ping

Add:

```text
session.ping
session.register
```

Expected result:

* Virtuoso plugin can connect to VFP Tunnel.
* Dashboard shows connected/disconnected status.

### Task 5: Implement Context Export

Virtuoso plugin extracts:

* lib
* cell
* view
* instance names
* master cell names
* basic instance parameters

VFP Tunnel stores it as:

```text
.vfp/contexts/latest_context.json
```

### Task 6: Implement Proposal Flow

Add proposal creation from JSON file:

```bash
vfp proposal create --file sample_proposal.json
```

Virtuoso dashboard can fetch and display pending proposal.

### Task 7: Implement Transactional Parameter Update

When a proposal is approved:

* capture before value;
* modify parameter;
* capture after value;
* save transaction JSON;
* refresh dashboard.

### Task 8: Implement Rollback

Rollback last transaction:

```bash
vfp transaction rollback <transaction_id>
```

or from Virtuoso dashboard.

### Task 9: Implement Result and Constraint Display

Add manual result ingestion first.

Example:

```bash
vfp result import --file result.json
vfp constraint check --file constraints.yaml
```

Virtuoso dashboard displays pass/fail result.

---

## 17. Definition of Done for MVP

The MVP is complete when the following flow works end-to-end:

1. Load plugin in Virtuoso.
2. Open dashboard.
3. Start VFP Tunnel.
4. Connect dashboard to tunnel.
5. Export current schematic context.
6. Create proposal externally.
7. Proposal appears inside Virtuoso.
8. User approves proposal.
9. Schematic parameter is modified.
10. Transaction is saved.
11. User can rollback.
12. Result JSON can be imported.
13. Constraints can be checked.
14. Dashboard displays latest metrics and pass/fail status.

---

## 18. Final Product Positioning

Virtuoso Flow Plugin should be developed as:

> A Virtuoso-native UI plugin for reviewable, transaction-based, and simulation-aware analog IC design automation.

VFP Tunnel should be developed as:

> An external bridge daemon that connects Virtuoso Flow Plugin to AI agents, CLI workflows, simulation infrastructure, and artifact management.

The combined system should prioritize safety, visibility, reversibility, and analog-design context awareness over unrestricted remote control.
