# AGENTS.md — working notes for AI agents

Conventions and environment notes for any agent (Claude Code, Codex, …)
working in this repository. The full plan is in [`project.md`](project.md);
status in [`docs/development_notes.md`](docs/development_notes.md).

## What this is

**Virtuoso Flow Plugin (VFP)** — a Cadence Virtuoso-embedded SKILL plugin
(`skill/`) plus an external Python bridge daemon **VFP Tunnel** (`tunnel/`)
for reviewable, transaction-based, agent-assisted analog IC design.
Monorepo by decision (shared contract in `schemas/`).

## Cadence / SKILL reference docs

A **partial** HTML mirror is committed at
`docs/IC231_gui_plugin_docs/` (sk* references only). Prefer it for quick
lookups, but it is incomplete.

The **authoritative, complete** IC23.1 help tree lives on the design
server and is the place to look when the local mirror lacks something:

| | |
|---|---|
| Host | `192.168.185.231` (CentOS 7) |
| User | `meow` — **SSH key login already configured** |
| Cadence root | `/opt/cadence` (`IC231`, `SPECTRE231`, `XCELIUM2309`) |
| Help tree | `/opt/cadence/IC231/doc` — **read-only** (247 component dirs) |
| SKILL refs | `/opt/cadence/IC231/doc/{skuiref,skdfref,sklangref,skcompref,skoopref,skipcref,sklayoutref,skpcellref,sktechfile,sktransrefOA,skillide,sklanguser,skdevref}` |

Files are HTML, one page per function, named like
`chap8_re_hiCreateAppForm.html`. Access is read-only — do not attempt to
write under `/opt/cadence`.

### How to look something up on the server

Find the page(s) for a function, then strip the HTML tags:

```bash
# locate a function's reference page
ssh meow@192.168.185.231 "ls /opt/cadence/IC231/doc/skuiref | grep -i hiCreateAppForm"

# print the signature/description as plain text
ssh meow@192.168.185.231 \
  "sed -e 's/<[^>]*>//g' /opt/cadence/IC231/doc/skuiref/chap8_re_hiCreateAppForm.html" \
  | grep -v '^[[:space:]]*$'

# full-text search across a reference set
ssh meow@192.168.185.231 "grep -rli 'hiInsertBannerMenu' /opt/cadence/IC231/doc/skuiref"
```

> SSH emits a harmless "post-quantum key exchange" warning to stderr;
> ignore it. Use `-o BatchMode=yes -o ConnectTimeout=10` for scripted calls.

## Build / run quick reference

Canonical source is this Windows repo (`F:/VBL/Virtuoso-Flow-Plugin`).
The user keeps a server-side working copy for loading into the VM's
Virtuoso at `/home/meow/Documents/VFP` (writable; `/opt/cadence` is not).
Sync changed `skill/*.il` there before reloading in Virtuoso.

```lisp
; Load the plugin inside the Virtuoso CIW (from the server-side copy)
load("/home/meow/Documents/VFP/scripts/load_vfp.il")
```

```bash
# VFP Tunnel (skeleton)
cd tunnel && pip install -e .[dev] && vfp --version
```

## Conventions

- **Verify SKILL API signatures against the IC23.1 docs** (local mirror or
  the server above) before using them — do not guess.
- SKILL paths use forward slashes, even on Windows.
- The data contract (context / proposal / transaction / result /
  constraint) is canonical under `schemas/`; keep both sides in sync there
  rather than duplicating per component.
- Agents never get unrestricted `evalstring`; schematic changes go through
  the transaction-aware wrappers and require user approval (see
  `project.md` §11).
