# omni

Design/implementation reference for **iceagentkit** (a shared platform for Omnigent + Headroom setup) and **polly-pipe** (its first module: a plan-to-PR agentic workflow).

- **`PRD-omnigent-headroom-workflow.md`** — the full PRD. Start here: it documents the platform/module split, every verified fact about Omnigent and Headroom's real capabilities (not just their marketing sites), and the open items still needing validation before implementation.
- **`polly-pipe/orchestrator-config.yaml`** — polly-pipe's Omnigent custom-agent definition (the actual workflow logic).
- **`polly_pipe/skills/board.py`** — the one real Python function tool the orchestrator calls, reporting task state into iceagentkit's shared dashboard.

`iceagentkit` was originally named `flowctl` during early design; the PRD's intro note explains the rename and the reasoning behind splitting a reusable platform layer out from the workflow-specific module.
