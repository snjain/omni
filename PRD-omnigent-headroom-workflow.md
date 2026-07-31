# PRD: icemetaagents Platform + polly-pipe Module (Omnigent + Headroom)

> **Naming history**: this document originally specified a single tool called `flowctl`. It has been restructured into two layers: **icemetaagents**, a shared platform for any module that needs Omnigent + Headroom set up, and **polly-pipe**, an independent module (the first one) that implements everything `flowctl` used to do end-to-end — the plan-to-PR workflow. Every `flowctl` reference below has been reassigned to whichever layer actually owns that responsibility. This split exists so future modules (not yet designed) can reuse the platform setup without re-implementing Omnigent/Headroom installation and wiring from scratch.

## 1. Summary

**icemetaagents** is the platform layer: it installs and wires Omnigent (multi-agent session harness) and Headroom (lossless context-compression middleware) once, exposes a global compression on/off switch, and runs a shared local API + dashboard framework (web + TUI) that independent modules register their own views into.

**polly-pipe** is the first module built on that platform. It implements the plan-to-PR agentic workflow: users describe a goal in freeform text; an agent turns it into a detailed plan through human-reviewed iteration; once approved, the plan is decomposed into a dependency-aware task board where each task is implemented and reviewed by AI models (assigned via Omnigent's router), with humans gating the two points where real work/spend begins — plan finalization and task-board finalization ("the paid turn"). Every session polly-pipe runs goes through Headroom's compression layer via the platform's wiring.

## 2. Goals

### Platform (icemetaagents)
- Install and wire Omnigent + Headroom once; any module reuses that setup rather than repeating it.
- Provide one global compression on/off/status switch, shared across all modules (see §9.2, §13.1).
- Run a shared local API + dashboard framework (web + TUI) that modules register their own data/views into, rather than each module standing up its own server.
- Maintain a module registry (`icemetaagents module add/list/remove`) so installing a new module is a single step once the platform is set up.

### Module (polly-pipe)
- Turn a freeform requirement into a reviewed, human-approved implementation plan.
- Decompose the approved plan into a task board of discrete, dependency-linked tasks.
- Auto-assign an implementor model and a reviewer model per task via Omnigent's model router, based on task complexity signals.
- Execute tasks (parallel where dependencies allow) producing one PR per task, with AI review before human escalation on failure.
- Give humans visibility and control: cost, tokens, compression savings, status, and dependencies per task; ability to run step-by-step or continuously.

## 3. Non-Goals / Out of Scope

- Concrete complexity-scoring algorithm/weights (signals are named; scoring rubric is left to Omnigent's own `sys_advise_models` recommendation, see §10).
- UI mockups / wireframes (a separate design artifact, not this PRD).
- Detailed sequence diagrams beyond the architecture diagram in §11.
- Design of any module beyond polly-pipe — future modules are referenced only to justify the platform/module split (§11.1), not specified here.

## 4. Actors (polly-pipe module)

| Actor | Type | Role |
|---|---|---|
| Requirements author | Human | States the goal in freeform text, answers clarifying questions |
| Planning Agent | AI | Drafts the plan, answers clarifying questions, incorporates human edits each round |
| Plan Approver | Human | Directly edits the plan draft; gives final approval to finalize it |
| Composer (Decomposer) Agent | AI | Breaks the finalized plan into a task board with dependencies and complexity signals |
| Task Board Reviewer Agent | AI | Reviews the Composer's task board for coverage, correctness, dependency sanity |
| Model Router | Omnigent built-in (`sys_advise_models`) | Assigns implementor + reviewer model per task from complexity signals and policy |
| Implementor (per task) | AI, model-routed | Executes the task inside an Omnigent session wrapped by Headroom; opens the task's PR |
| Task Reviewer (per task) | AI, model-routed | Reviews the task's PR; approves or rejects |
| Execution Approver | Human | Approves the finalized task board and authorizes the "paid turn" (spend) before execution starts; resolves escalations |

## 5. Workflow (polly-pipe module)

### Phase 1 — Requirements Intake
- User provides a freeform description of the goal.
- Planning Agent asks clarifying questions iteratively until it has enough to draft a plan.
- Output: a confirmed requirements brief.

### Phase 2 — Plan Generation & Review (human-in-the-loop)
- Planning Agent drafts a detailed plan from the brief.
- Human can **directly edit** the plan draft (not just approve/reject).
- Edited draft goes back to the Planning Agent to reconcile/re-draft affected sections.
- Rounds are **unlimited** — repeats until the human gives explicit "Approve & Finalize."
- Output: a finalized, versioned Plan (immutable once approved).

### Phase 3 — Task Decomposition (Composer)
- Composer Agent breaks the finalized Plan into discrete tasks.
- Each task is tagged with complexity signals: number of files touched, estimated change size, dependency fan-in/out, risk classification.
- A task dependency graph (DAG) is established.
- Omnigent's model router assigns an **Implementor model** and a **Reviewer model** per task.
- Output: a draft Task Board.

### Phase 4 — Task Board Review & Finalization (human-in-the-loop)
- Task Board Reviewer Agent evaluates the Composer's decomposition: plan coverage, dependency correctness, model-assignment reasonableness.
- Composer and Reviewer **must reach agreement** with each other before the board is presented to the human.
- Human reviews the agreed board: **approve or reject-with-comments only** — no direct field edits.
- A distinct, explicit second human gate: approval of **"the paid turn"** — authorizing actual spend before any task execution begins, shown alongside a projected cost estimate.
- Output: Finalized Task Board, execution authorized.

### Phase 5 — Execution
- Two execution modes, selectable by the human:
  - **Step mode**: execute every currently-dispatchable task once, then pause for human input.
  - **Continuous mode**: keep dispatching as tasks become ready until blocked or all done.
- **Concurrency**: tasks with satisfied dependencies may run in parallel, bounded by `guardrails.policies.spawn_bounds.max_dispatches_per_turn` (§11); dependent tasks wait on their prerequisites.
- Each Implementor runs inside an Omnigent agent session, with all model traffic wrapped by Headroom's compression layer (platform-provided, see §9.2).
- On completion, the Implementor opens **one PR per task**. Humans always merge; agents never do (confirmed convention, see §9.3).
- The task's Reviewer model reviews the PR:
  - **Approved** → task status = Done.
  - **Rejected** → task status = Rejected-Needs-Human, **escalated to a human** — no automatic retry.
- The board updates live: status, cost, tokens, compression savings, PR link.

## 6. Task Board — Data Model (polly-pipe's schema, registered into the platform dashboard)

| Column | Description |
|---|---|
| Task ID / Title | Identifier and short description |
| Status | Pending · Blocked-on-dependency · Assigned · In-Progress · In-Review · Rejected-Needs-Human · Done · Cancelled |
| Implementor | Model assigned by the router |
| Reviewer | Model assigned by the router |
| Cost | Actual spend for the task ($) |
| Tokens consumed | Raw token count |
| Compression savings | Tokens saved / % reduction, via Headroom — shown per task |
| PR | Link + PR status (open/merged/closed) |
| Dependencies | List of prerequisite task IDs; rendered as a DAG/graph view on the board |

## 7. Open Technical Questions

- **Concurrency limits**: exact max concurrent tasks / cost-throttling values are a config choice at implementation time (`spawn_bounds.max_dispatches_per_turn`).
- **Complexity → model mapping**: left to `sys_advise_models`' own recommendation at dispatch time, not a bespoke rubric.
- **Module registration contract** (§11.1): the exact manifest format a module provides to `icemetaagents module add` is not yet specified — polly-pipe is the reference case to design it against, not an already-defined interface.

## 8. Assumptions

- Omnigent and Headroom are used as-is (third-party products); icemetaagents is a platform layer built on top, not a fork/modification of either.
- Omnigent's `sys_advise_models` is the mechanism used for per-task model assignment — polly-pipe supplies the complexity signals, Omnigent's router makes the assignment.
- "Paid turn" refers to the transition from planning (cheap/iterative) to task execution (real spend across potentially many models/tasks).

---

# Implementation Reference (session findings)

Everything below was verified against the two products' actual public sites, GitHub repos, and source files (not just marketing copy) during design discussion, and is kept here so implementation can proceed without re-deriving it.

## 9. Verified Product Facts

### 9.1 Compatibility matrix (verified against source, not marketing pages)

The public homepages undersell both products' actual reach — the real repos list more:

| Tool | Headroom | Omnigent |
|---|---|---|
| Claude Code | ✅ | ✅ |
| Codex | ✅ | ✅ |
| Cursor | ✅ | ✅ (homepage omits this; the real repo's README lists it) |
| OpenCode | not named | ✅ (`omnigent opencode`) |
| Hermes, Pi, Antigravity | not named | ✅ |
| GitHub Copilot | ❌ | ❌ |

**GitHub Copilot is not supported by either product** — no combination of Omnigent+Headroom covers it. If Copilot support is a hard requirement, that's a gap neither vendor closes.

### 9.2 Headroom ↔ Omnigent wiring (platform-owned, resolved with a correction)

Neither product's docs mention the other by name, but the mechanism to connect them is real and documented on each side independently:

- **Omnigent's Gateway** accepts "any OpenAI- or Anthropic-compatible `base_url` and key" (examples given: OpenRouter, Ollama). Configured via `omnigent setup`.
- **Headroom's proxy mode** (`headroom proxy --port 8787`) serves both Anthropic `/v1/messages` and OpenAI-compatible `/v1/chat/completions`/`/v1/responses` routes locally, compressing transparently before forwarding to the real provider.

**Wiring**: point Omnigent's `base_url` override(s) at `http://localhost:8787` (Headroom's proxy). Every model call routed through it gets compressed before reaching the real provider. **This wiring is done once by icemetaagents during platform setup — every module, including polly-pipe, inherits it automatically.**

**Correction — this is likely not one unified knob.** Earlier drafts of this PRD described a single "Gateway `base_url`" setting. Searching Omnigent's source shows separate, narrower overrides instead: general provider vars (`ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`) plus per-harness gateway vars (`HARNESS_PI_GATEWAY_BASE_URL`, `HARNESS_QWEN_GATEWAY_BASE_URL`, and presumably others per harness). Whether `omnigent setup` unifies these into one config entry for you, or you'd need to set several independently, is **not yet confirmed** — flag as a §16 item: enumerate the full set of base_url-style knobs before implementation.

**Unverified assumption (needs a PoC before relying on it, see §16)**: whether Omnigent's Gateway sits in the request path for *every* harness session (Claude Code, Cursor, OpenCode, etc.) or only for Omnigent's own built-in/custom agents. If it's the latter, only a module's orchestrator "brain" calls get compressed, not the sub-agent harnesses' calls.

**Design decision — icemetaagents presents one global switch regardless.** Even though the underlying knobs may be per-provider/per-harness, icemetaagents deliberately does not expose that granularity to the user. `icemetaagents compression on` / `icemetaagents compression off` sets or unsets *every* known base_url override together, so compression is a single on/off decision from the user's point of view, shared across every installed module — see §13.1. The risk this creates: if a new harness's gateway var isn't in icemetaagents' known list, toggling "off" could leave that one harness still routed through Headroom, silently breaking the "global switch" promise. §16 needs an explicit, versioned list of every override icemetaagents must touch, kept in sync as Omnigent adds harnesses.

### 9.3 Distribution & licensing

| | Headroom | Omnigent |
|---|---|---|
| Distribution | `pip install "headroom-ai[all]"` | `curl -fsSL https://omnigent.ai/install.sh \| sh` or `uv tool install omnigent` |
| License | Apache 2.0, open source | Apache 2.0, open source |
| Repo | github.com (search `headroom-ai`) | `omnigent-ai/omnigent` |

Both Apache 2.0 → bundling/redistribution is legally permitted; must retain each project's `LICENSE`/`NOTICE` and mark any modifications. No requirement to open-source icemetaagents' or polly-pipe's own code.

**PR merge convention (confirmed via `examples/polly/config.yaml`)**: implementer sub-agents always open their own PR and never merge; the human merges. polly-pipe adopts this as-is — no auto-merge.

### 9.4 Omnigent's session storage (`chat.db`) — and why modules don't write into it

Confirmed directly in `omnigent-ai/omnigent`'s source (`docs/omni-upgrade-design.md`): *"All durable state lives in sqlite (`~/.omnigent/chat.db`), not in [the server/daemon] — server/daemon [is] safe to stop and respawn; they rehydrate from sqlite."* Locally this defaults to `~/.omnigent/chat.db`; hosted deployments (Fly, Render, HF Spaces, Cloudflare) can point `DATABASE_URL`/`--database-uri` at Postgres instead, since SQLite doesn't hold up under concurrent multi-instance access (Modal's own docs explicitly rule out a SQLite tier for that reason).

`chat.db` holds more than literal chat messages — sessions, conversations, agents, files, policies, permissions, comments, and scheduled tasks each have their own store module (`omnigent/stores/{agent,artifact,comment,conversation,file,permission,policy,project,scheduled_task}_store`), all backed by the same SQLite file by default.

**Checked whether a module could add its own table into `chat.db` — no sanctioned way to do that:**
- `omnigent/stores/` is a **fixed, closed list** of store modules, not a plugin registry.
- Searched the repo for `"custom store"` and `register_store` — zero matches. No hook exists for registering a new store/table.
- The schema is Alembic-migration-managed by Omnigent's own release process (`omnigent/db/migrations/versions/...`); an externally-added table would sit outside that history, with no compatibility guarantee across Omnigent upgrades, and risks lock contention with Omnigent's own server process as a second uncoordinated writer.

**Decision: each module maintains its own separate SQLite database under the platform's data directory**, fully owned and schema-controlled by that module, independent of Omnigent's release cycle. polly-pipe's board lives at `~/.icemetaagents/modules/polly-pipe/board.db`:
- **No standing server sits in front of it.** `record_board_state` (running inside the orchestrator's own process) writes directly to `board.db` — it's the sole writer, so there's no concurrent-write hazard to design around. This replaced an earlier draft of this PRD that routed writes through a persistent local API server; that hop added a process and a port for no benefit once the single-writer property was recognized (see §11/§13.2/§14 for the revised, server-light design).
- Dashboards **read** the same file — the TUI opens it read-only and polls (task state doesn't change sub-second, so polling is sufficient — no push infrastructure needed); the web dashboard, when used, is served by an on-demand process rather than a persistent one (§14).
- Optional, read-only correlation: a dashboard reader may separately open `~/.omnigent/chat.db` **read-only** to pull session/conversation metadata by `session_id`/`conversation_id` for display alongside a task — never as a write target.
- A future module gets its own `~/.icemetaagents/modules/<name>/*.db`, namespaced the same way — no shared schema to coordinate across modules, and no shared server to keep running either.

### 9.5 Graphify — verified facts (third-party, optional)

Checked against `Graphify-Labs/graphify` on GitHub, not just its marketing page:

- **What it is**: a local, deterministic AST-based (tree-sitter) code knowledge graph builder — no vector store, no cloud, no API keys, no LLM tokens spent building the graph. Apache 2.0, same licensing posture as Omnigent and Headroom.
- **Distribution**: `uv tool install graphifyy` (note the double `y` — that's the actual package name), then `graphify install`.
- **Compatibility**: ships a `/graphify` skill for Claude Code, Cursor, Codex, and Gemini CLI. Not Omnigent-specific — but works inside an Omnigent session anyway, because Omnigent's `claude-sdk` executor reads host skills from `~/.claude/skills/` (the same path Polly's own config warns against writing into), so it wraps the harness's native skill discovery rather than replacing it.
- **Storage**: `graph.json` on disk (plus `graph.html` and `GRAPH_REPORT.md`), no database required for basic use; optional Neo4j/FalkorDB export.
- **Three integration mechanisms**: (1) direct CLI (`graphify query/path/explain`), (2) an **MCP server** (`python -m graphify.serve graph.json`, exposing `query_graph`/`get_node`/`get_neighbors`/`shortest_path` — this is the mechanism a module's agent config declares as a `type: mcp` tool, §11.2), (3) "nudge" hooks that fire before file-read/search tool calls to steer an agent toward `graphify query` instead of grepping (Claude Code/Gemini CLI/CodeBuddy via PreToolUse-style hooks; Cursor/Codex via persistent instruction files like `.cursor/rules/graphify.mdc`).
- **No published token-savings numbers.** The README's only cost claim is that graph *construction* costs 0 LLM credits (local parsing, no model calls) — it does not benchmark query-time token savings versus grep. The mechanism (returning a scoped subgraph instead of full file reads) is architecturally sound for reducing tokens spent on code-relationship questions, but treat any specific multiplier as unverified — including third-party claims (e.g. a community "71.5x fewer tokens" repo) that combine Graphify with unrelated tooling and aren't Graphify-Labs' own benchmark.
- **Disabling has no partial state**: the nudge hooks (the only "always-on" piece) have no dedicated off switch — only full or per-platform `graphify uninstall`. The skill and MCP tool are already inherently opt-in (only used if invoked/declared), so nothing to disable there.
- **Separate git-hook mechanism** (`graphify hook install/uninstall/status`, post-commit/post-checkout) exists to keep the graph in sync with code changes — distinct from the nudge hooks above, not yet verified for reliability under polly-pipe's parallel-worktree execution model (§16 item 8).

### 9.6 RTK — verified facts (third-party, optional)

Checked against `rtk-ai/rtk` on GitHub:

- **What it is**: a single Rust binary, zero dependencies, that intercepts *shell command output* (not model traffic) and compacts it before it enters an agent's context — condensed `git status`, failures-only test output (Jest/pytest/cargo test/go test), grouped lint/build errors, filtered package-manager/cloud/container CLI output. Claims "up to 90% of the bash output your agent reads," with an explicit, unusually honest disclaimer: *"it is not the same as cutting your bill by 90%."* Apache 2.0.
- **Distribution**: Homebrew, a quick-install script, `cargo install`, or prebuilt binaries — a fourth distribution mechanism distinct from Headroom (pip), Omnigent (installer script), and Graphify (`uv tool`).
- **A third, distinct token-reduction layer, not a duplicate of Graphify or Headroom**: Graphify reduces tokens needed for code-*relationship* questions (replacing grep/reads with graph queries); RTK reduces tokens from noisy *shell/CLI output* (replacing raw command output with compacted output); Headroom compresses whatever content actually reaches the model regardless of source. All three stack.
- **Compatibility**: 15 agents, including every harness polly-pipe dispatches to (Claude Code, Cursor, Codex, OpenCode, Hermes, Pi) plus GitHub Copilot, Windsurf, Cline/Roo Code, Antigravity, and others. **Does not close the Copilot gap for this stack** — RTK working with Copilot is unrelated to Omnigent, which still doesn't support Copilot as a harness (§9.1 unaffected).
- **No MCP server, no REST API** — CLI-first only (`rtk git status`, `rtk cargo test`, ...) plus native per-agent hook installation (`rtk init -g` for Claude Code, equivalent for the other 14). Unlike Graphify, there's no `type: mcp` tool to declare in a module's YAML — opting in means installing the native hook per harness and instructing the orchestrator's prompt to prefix relevant shell commands with `rtk`.
- **Real limitation on Claude Code specifically**: the hook only rewrites `Bash` tool calls — `Read`/`Grep`/`Glob` bypass it entirely, requiring explicit `rtk read`/`rtk grep`/`rtk find` instead. The benefit is conditional on the orchestrator's prompt actually instructing that substitution, not automatic.
- **Fits polly-pipe's Execute phase concretely**: Polly's own prompt already requires implementors to run tests/lint/typecheck and reconcile exact test counts — exactly the noisy output RTK targets — so wrapping those dispatch-time commands would reduce the `tokens`/`cost_usd` `record_board_state` reports per task, in the phase the paid-turn gate is spend-gating.
- **Own analytics**: `rtk gain` is a built-in token-savings dashboard. Worth having `record_board_state` pull from it as a second savings source alongside Headroom's `compression_saved_tokens`, not just Headroom's number alone.
- **Disabling has no partial state, same as Graphify**: uninstall is `rtk init -g --uninstall` (removes hook, `RTK.md`, `settings.json` entry; optionally `cargo uninstall rtk`/`brew uninstall rtk` for the binary itself). No global pause env var for the core filtering (only `RTK_TELEMETRY_DISABLED=1`, which is telemetry-only). No per-command bypass flag — only a static, pre-configured `exclude_commands` list in `~/.config/rtk/config.toml`. Once a hook is installed, every matching Bash call is rewritten with no per-invocation escape hatch.
- **Telemetry**: opt-in, disabled by default, anonymous aggregate metrics (device hash, OS/version, command/token counts, tool names only — no arguments or secrets). Managed via `rtk telemetry enable/disable/forget`.

**Pattern worth naming explicitly**: this is the second optional capability (after Graphify) whose only real lever is full install/uninstall, not a lightweight pause. Headroom's toggle is genuinely light (an env var/config flip); Graphify and RTK are not. Treat this as the default assumption for any *future* optional capability icemetaagents adds — the platform's job is to consistently wrap "vendor only offers install/uninstall" behind a clean `on/off/status` UX, not to expect a lighter switch to already exist.

## 10. Omnigent Extensibility Model

Checked directly against the `omnigent-ai/omnigent` codebase (not inferred): **there is no plugin, hook, extension, or middleware system** — searched the repo for all four terms, zero matches. The only two extension surfaces are:

1. **Custom agents** — a YAML file (`spec_version`, `name`, `prompt`, `executor`, `tools`, `guardrails`, ...) invoked via `omnigent run path/to/config.yaml`. No alias/registry exists; there's no way to invoke a custom agent as a short top-level command like a built-in harness. (icemetaagents' module registry, §11.1, is what supplies that convenience — Omnigent itself doesn't.)
2. **The Gateway config** — the `base_url`/key override described in §9.2, the only way to intercept/redirect model traffic.

Within a custom agent, two categories of extension are easy to conflate — they are **not** the same thing:

| | Skills | Function tools |
|---|---|---|
| What it is | **Prose** (`SKILL.md`), loaded via the `Skill` tool mid-conversation | Real Python, referenced by dotted import path |
| Where it lives | `<agent-dir>/skills/<name>/SKILL.md` — never the host `~/.claude/skills/` | An installed, importable Python package (e.g. `pip install -e .`) on the same environment the agent's executor runs in; referenced as `callable: polly_pipe.skills.board.record_board_state` in the YAML `tools:` block |
| Confirmed by | Polly's own config: *"skills are prose, not code... A skill always belongs in polly's OWN skills directory"* | Polly's guardrails reference `path: omnigent.inner.nessie.policies.blast_radius` — a plain dotted import path |
| Used for | Reusable instruction modules (Polly has `investigate`, `fanout`, `cross-review`) | Anything that must reliably *do* something outside the model's own reasoning — polly-pipe's only use case is `record_board_state` |

**Sessions are interactive/multi-turn**, not one-shot/headless — confirmed. This is why the PRD's human-approval gates (plan, board, paid-turn) don't need a separate polling/blocking mechanism: the orchestrator's `prompt` just says "present X, then wait for the human's reply," and the session naturally blocks there.

### 10.1 Adding more agents going forward (within a module)

Two paths, both confirmed against real Omnigent config structure:

- **Static roster member** (a permanent, named, roster-preflighted sub-agent role): add `agents/<name>/config.yaml` (same schema as the orchestrator itself — see `examples/polly/agents/claude_code/config.yaml` and `.../pi/config.yaml`, which are nearly identical aside from `executor.config.harness`), add `<name>` to `tools.agents` in the orchestrator's YAML, extend the roster-preflight check and `guardrails.policies` as needed.
- **Dynamic/ad-hoc agent** (a one-off, narrowly-scoped helper): set `spawn: true` on the orchestrator (already in polly-pipe's template in this repo) — this registers `sys_session_create`, which lets the orchestrator author a brand-new agent config at runtime and launch it via `config_path`, with **no static YAML change required**. Recommended default for anything not part of the fixed roster.

This is distinct from adding a whole new **module** (§11.1), which is a platform-level registration, not an agent-roster change within one module.

## 11. Final Architecture — Platform / Module Split

All orchestration logic for the plan-to-PR workflow (plan, decompose, dispatch, cross-model review, PR creation, all three approval gates) lives **inside Omnigent** as polly-pipe's custom agent, invoked purely via `omnigent run`. icemetaagents is deliberately thin at the platform level too — it exists to do once, for every module, the things Omnigent structurally cannot host itself: installation/wiring and a global compression switch. It does **not** run a persistent dashboard server (see the revision note below) — dashboards read module state directly.

**Revision — dropped the persistent local API/state server.** An earlier draft of this architecture put a standing HTTP server (`:7878`) between `record_board_state` and each module's SQLite file, to support live-push updates to the dashboard. On review this added a process and a port for no real benefit: `record_board_state` is the *sole* writer to its module's database (no concurrent-write hazard to mediate), and task-board state doesn't change fast enough to need push updates — polling a SQLite file every second or two is indistinguishable in practice. The server is gone; see §13.2/§14 for the resulting design.

```
                         ┌─────────────────────────────────────────┐
                         │            YOU (human)                   │
                         │  talks to orchestrator · watches board    │
                         └───────────┬───────────────┬───────────────┘
                                     │               │
                     interactive session          reads/polls
                     (plan review, board                │
                      approval, paid-turn,               ▼
                      rejection escalation)     ┌──────────────────────┐
                                     │           │  polly-pipe dashboard  │
                                     ▼           │  TUI: reads board.db    │
                    ┌────────────────────────┐   │  directly, read-only,   │
                    │   omnigent run          │   │  polls every ~1-2s      │
                    │   polly-pipe's           │   │  Web (--web): on-demand │
                    │   orchestrator/config.yaml│   │  local process, same    │
                    │   (custom agent, forked  │   │  read-only queries,      │
                    │    from Polly's pattern) │   │  exits when closed       │
                    │                          │   └──────────┬────────────┘
                    │  record_board_state()    │              │ read-only,
                    │  writes directly to       │              │ no push
                    │  ~/.icemetaagents/modules/│              │
                    │  polly-pipe/board.db      │◀─────────────┘
                    └───────────┬────────────────┘
                                │ dispatches sub-agents
                                │ into parallel worktrees
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │   HARNESSES (implementor / reviewer sub-agents)          │
        │   Claude Code · Codex · Cursor · OpenCode · Pi · Hermes    │
        └───────────────────────────┬───────────────────────────┘
                                     │ every model call from every
                                     │ harness + the orchestrator itself
                                     ▼
                    ┌────────────────────────────┐
                    │   OMNIGENT (the host)         │
                    │   sessions, sandboxing,        │
                    │   base_url overrides           │
                    │   (wired once by icemetaagents) │
                    └───────────┬────────────────────┘
                                │ overrides point here
                                ▼
                    ┌────────────────────────────┐
                    │   HEADROOM proxy               │
                    │   (localhost:8787) — compresses  │
                    │   every request, lossless          │
                    └───────────┬────────────────────────┘
                                │ forwards compressed request
                                ▼
                    ┌────────────────────────────┐
                    │   REAL MODEL PROVIDER          │
                    │   Anthropic / OpenAI / etc.      │
                    └────────────────────────────────┘

        Implementor sub-agents also open PRs directly on GitHub
        (one per task; humans merge, agents never do).
```

**Standing ports, revised**: just two run persistently regardless of what we build — Headroom's proxy (`:8787`) and Omnigent's own web UI (`:6767`, which runs whether or not any module uses it). polly-pipe's web dashboard uses a port only transiently, while `--web` is open; the TUI uses none.

| Component | What it is | Layer | Built by this project? |
|---|---|---|---|
| Headroom | Third-party pip package, proxy on :8787 | — | No |
| Omnigent | Third-party meta-harness, own web UI on :6767 | — | No |
| Harnesses (Claude Code, Codex, Cursor, OpenCode, Pi, Hermes) | Third-party coding agents | — | No |
| Installer/setup, compression toggle | Installs Headroom + Omnigent once, wires base_url overrides, `compression on/off/status` | **icemetaagents (platform)** | **Yes** |
| Module registry | `icemetaagents module add/list/remove` | **icemetaagents (platform)** | **Yes** |
| Orchestrator agent (`config.yaml` + skills) | polly-pipe's custom Omnigent agent, forked from `examples/polly`; `record_board_state` writes `board.db` directly | **polly-pipe (module)** | **Yes** — see `polly-pipe/orchestrator-config.yaml` in this repo |
| Dashboard (TUI always available; web on-demand) | Reads `board.db` directly, read-only, polling — no server in the write path, and no server at all for the TUI | **polly-pipe (module)** | **Yes** |
| GitHub | External | — | No |

### 11.1 Module contract — what a future module needs to provide

This is new, unspecified surface (§7 flags it as an open question) — captured here as a starting design, not a finished interface:

**icemetaagents (platform) guarantees to every module:**
- Omnigent installed, and Headroom + Graphify + RTK installed and wired **if enabled** — all three are optional at platform setup, none forced (§11.2).
- A global compression toggle the module doesn't need to reimplement.
- Isolated storage under `~/.icemetaagents/modules/<module-name>/` — no server required to use it; a module writes directly to its own SQLite file.

**A module must provide, to be registered via `icemetaagents module add <name>`:**
- An Omnigent-invocable agent directory (`config.yaml` + optional `skills/*/SKILL.md`), same shape as polly-pipe's.
- Any function-tool Python package it needs (e.g. polly-pipe's `record_board_state`), pip-installed into the same environment Omnigent's executor runs in.
- Optionally, a view/schema registration for the shared dashboard (polly-pipe's is the task-board columns in §6) — a module that doesn't need a structured board can skip this and rely purely on the conversational session.
- Its own CLI entrypoint if it wants one (polly-pipe ships `polly-pipe start`/`polly-pipe board`, both thin wrappers — see §13.2), independently pip-installable, so a module works standalone or via `icemetaagents run <module-name>`.
- If it wants Graphify, an explicit opt-in — declaring the `graph: { type: mcp, ... }` tool entry in its own agent config (§11.2). If it wants RTK, an explicit opt-in of a different shape — installing RTK's native per-harness hooks and instructing its own prompt to use `rtk`-prefixed commands (§9.6), since there's no tool declaration for it the way there is for Graphify. Neither is ever assumed on just because the platform has it installed.

### 11.2 Optional capabilities — Headroom, Graphify, and RTK, at both the platform and module level

None of Headroom, Graphify, or RTK is mandatory for icemetaagents or for any module. All three are opt-in at two independent points, and they land differently at the module level — worth being precise about the asymmetry rather than implying uniform control that doesn't exist yet:

| | Platform-level opt-in | Module-level opt-in |
|---|---|---|
| **Headroom (compression)** | `icemetaagents setup` asks whether to install/wire it at all; once wired, `icemetaagents compression on/off/status` toggles it (§9.2, §13.1) | **Not currently possible.** Compression is global across every module and plain `omnigent` usage alike — there is no per-module override today. Making it selective would need the per-harness/per-provider override granularity flagged as unverified in §16 item 3. Treat "compression on for polly-pipe but off for another module" as an unimplemented stretch goal, not a supported configuration. |
| **Graphify (code graph)** | `icemetaagents setup` asks whether to install it (`graphify install`); `icemetaagents graphify on/off/status` toggles it — "off" is a full `graphify uninstall` under the hood, no lighter state exists (§9.5) | **Already naturally supported** — a module simply declares (or omits) the `graph: { type: mcp, url: ... }` tool entry in its own `orchestrator-config.yaml`. Graphify being installed platform-wide doesn't force any module to use it; each module's YAML is the real switch. |
| **RTK (shell output compaction)** | `icemetaagents setup` asks whether to install it; `icemetaagents rtk on/off/status` toggles it — same as Graphify, "off" is a full `rtk init -g --uninstall` per harness, no partial-disable state exists (§9.6) | **Supported, but by prompt instruction rather than a tool declaration** — no MCP server to declare. A module opts in by installing RTK's native hook for the harnesses it dispatches to and instructing its orchestrator's prompt to prefix relevant shell commands with `rtk`. Omitting both means RTK stays inert for that module even if installed platform-wide. |

**Setup flow** (all three prompted at `icemetaagents setup`, none forced):
```
icemetaagents setup
  ? Enable Headroom compression for all Omnigent traffic? [Y/n]
  ? Install Graphify (local code knowledge graph)? [Y/n]
  ? Install RTK (shell/CLI output compaction)? [Y/n]
```
**Module registration flow** (Graphify and RTK only, since compression has no module-level knob yet):
```
icemetaagents module add polly-pipe
  ? Graphify is installed on this platform. Use it for polly-pipe's
    dependency analysis and explore/search dispatches? [Y/n]
    (writes, or omits, the `graph:` tool entry in polly-pipe's orchestrator-config.yaml)
  ? RTK is installed on this platform. Wrap test/lint/build/git commands
    in polly-pipe's dispatches with it? [Y/n]
    (installs RTK's native hook for claude_code/codex/opencode/cursor/hermes/pi,
    and adds the rtk-prefix instruction to the orchestrator's prompt)
```

## 12. Implementation Files (in this repo)

- **`polly-pipe/orchestrator-config.yaml`** *(renamed from `flowctl-orchestrator-config.yaml`)* — polly-pipe's orchestrator agent template: five-phase prompt (plan → decompose → board review → paid-turn → execute), `spawn: true` for dynamic sub-agents, `record_board_state` function-tool wiring, guardrails (`blast_radius`, `spawn_bounds`, `headless_subagent_purpose_guard`) reused from Omnigent's own reference orchestrator. Placeholders marked `[Reuse polly's proven prose verbatim for: ...]` should be filled by copying the matching sections from `examples/polly/config.yaml` in the `omnigent-ai/omnigent` repo rather than re-deriving them.
- **`polly_pipe/skills/board.py`** *(renamed from `flowctl_skills/board.py`)* — the one real Python function tool (`record_board_state`), writing task state directly to `board.db` (no API hop — see §11's revision note). This is the only custom code referenced from the orchestrator's `tools:` block; everything else in the YAML is prose.
- Sub-agent configs (`claude_code`, `codex`, `opencode`, `cursor`, `hermes`, `pi`) need **no changes** from Omnigent's own `examples/polly/agents/<name>/config.yaml` — board reporting is orchestrator-side only, and lives with polly-pipe, not with any other module.

## 13. Installation & CLI UX

### 13.1 Platform (icemetaagents)

```bash
curl -fsSL https://icemetaagents.dev/install.sh | sh   # pip-installs headroom-ai,
                                                          # installs omnigent

icemetaagents setup      # collects provider/GitHub keys, spend caps, concurrency limit;
                           # asks Y/n on Headroom compression, Graphify, and RTK (§11.2) —
                           # all three optional, none forced; if Headroom is enabled, starts
                           # its proxy and wires Omnigent's base_url overrides to it — no
                           # dashboard server to start, there isn't one (§11)

icemetaagents doctor      # fires a dummy session through Omnigent and confirms Headroom's
                           # proxy actually saw and compressed the traffic — the built-in
                           # version of the §16 PoC, so it's checkable on every install
                           # (skipped/no-op if compression wasn't enabled)

icemetaagents compression on | off | status   # global switch, shared across every
                                                # installed module — see §9.2. Platform-level
                                                # only; no per-module override exists (§11.2)

icemetaagents graphify on | off | status   # installs/uninstalls Graphify platform-wide
                                             # ("on"/"off" here really means graphify
                                             # install / uninstall under the hood, since
                                             # Graphify itself has no lighter toggle — §16)

icemetaagents rtk on | off | status        # installs/uninstalls RTK's hooks platform-wide
                                             # ("off" is `rtk init -g --uninstall` per harness,
                                             # hook removal only — binary stays installed
                                             # unless `--purge` is also passed; §9.6)

icemetaagents module add polly-pipe    # registers a module (installs its agent + skills,
                                         # per the §11.1 contract); asks whether to wire
                                         # in Graphify and/or RTK for this module specifically,
                                         # for whichever of the two are installed platform-wide (§11.2)
icemetaagents module list
icemetaagents module remove polly-pipe
```

**Deliberately a single global compression switch, not per-harness controls** — icemetaagents always sets/unsets the full known override list together (§9.2), even though Omnigent's underlying mechanism is more granular. `status` exists specifically to catch the failure mode where a new harness's override isn't in the known list yet and gets missed by a toggle. **Graphify's and RTK's switches are coarser still** — neither vendor tool has a partial-disable state, so `off` is a full `graphify uninstall` / `rtk init -g --uninstall` under the hood in both cases, not a paused/inactive state (§9.5, §9.6). This is treated as the default assumption for any future optional capability, not a one-off quirk of these two (§9.6's closing note).

### 13.2 Module (polly-pipe)

Day-to-day, the actual plan/board/execution interaction happens **inside the interactive `omnigent run` session** (conversational, per §10) — polly-pipe does not reimplement `plan new`/`board create` as separate CLI business logic. Its own CLI surface is a thin, independently pip-installable wrapper:

```bash
polly-pipe start   # shorthand for: omnigent run ~/.icemetaagents/modules/polly-pipe/agents/orchestrator/config.yaml
polly-pipe board    # TUI by default: opens board.db read-only, polls every ~1-2s,
                      # no server process involved
polly-pipe board --web   # spins up a minimal, stateless, read-only HTTP process on
                           # demand (queries board.db per request, no in-memory state
                           # to keep in sync) and opens a browser tab against it; the
                           # process exits when the tab/command closes — nothing keeps
                           # running in the background afterward

# equivalently, via the platform once the module is registered:
icemetaagents run polly-pipe
```

## 14. Dashboard: TUI (default) + On-Demand Web

Revised from an earlier draft that had both as render layers on a persistent shared state-API server — that server added a process and a port with no real benefit once `record_board_state` was recognized as the sole writer to `board.db` (see §11's revision note). The current design:

- **TUI (default, no server at all)**: a local process (recommended: **Textual**, Python, matches the rest of the stack) opens `~/.icemetaagents/modules/polly-pipe/board.db` read-only and polls it every ~1-2 seconds. Task-board state doesn't change fast enough to need push updates, so polling is indistinguishable from push in practice, without the complexity.
- **Web (`--web`, on-demand only)**: since a browser can't open a local SQLite file directly, a minimal HTTP process is required here — but it's stateless (queries `board.db` per request, holds nothing in memory) and only runs while explicitly requested, not as a background service. Tradeoff to keep in mind: Omnigent's own selling point is session continuity across terminal → browser → phone; "check the board from my phone" only works while the on-demand web process happens to be running — if that matters as an always-available capability rather than an occasional one, it would need to become a persistent service again, reintroducing the port/process this revision removed.

## 15. Cost/Token/Compression Reporting

Sourced by polly-pipe's orchestrator from each sub-agent dispatch's result and included in the `record_board_state` call: `cost_usd`, `tokens` (raw), `compression_saved_tokens` (from Headroom, if the provider response surfaces it). Shown per-task on the board, not just aggregated at the plan level, per the original brief. Any future module reports its own metrics the same way, into its own dashboard view.

## 16. Remaining Unverified Assumptions — Do These Before Committing Further

1. **Gateway request-path scope** (§9.2): confirm Omnigent's base_url overrides actually intercept *every* harness's model calls, not just the orchestrator's own. Test: point the override(s) at a dummy logging server, dispatch a Cursor- or Claude-Code-orchestrated sub-agent task, confirm the dummy server sees it.
2. **`omnigent setup`'s config format**: inspect what it actually writes (e.g. `~/.omnigent/...`) so `icemetaagents setup` can pre-populate/patch it programmatically rather than requiring interactive input.
3. **Full enumeration of base_url-style overrides** (§9.2): confirmed so far — `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `HARNESS_PI_GATEWAY_BASE_URL`, `HARNESS_QWEN_GATEWAY_BASE_URL`. Unconfirmed — whether every other harness (Claude Code, Codex, Cursor, OpenCode, Hermes, Antigravity) has its own equivalent, and whether `omnigent setup` exposes one unified entry point for all of them or each must be set independently. This list is exactly what `icemetaagents compression on/off` needs to stay complete and correct — treat it as a living list, re-verified whenever Omnigent adds a harness.
4. **Cost/token/compression-saving surfacing**: confirm what Omnigent's dispatch results (or Headroom's own stats endpoint) actually expose per-call, since `record_board_state`'s `cost_usd`/`tokens`/`compression_saved_tokens` fields depend on this being real, retrievable data.
5. **Module contract (§11.1)**: this is a first draft, designed against polly-pipe as the only real example. It should be revisited once a second module is actually attempted — a one-module sample isn't enough to know which parts of the contract are genuinely general-purpose versus accidentally polly-pipe-shaped.
6. **SQLite concurrent read/write behavior** (§11, §14): confirm `board.db` is opened in WAL mode so the TUI/web dashboard's read-only polling doesn't hit "database is locked" against `record_board_state`'s writes. This is standard SQLite practice for a single-writer/multi-reader setup, but needs to actually be set when the DB is created, not assumed.
7. **Per-module compression control** (§11.2): today compression is platform-global only — confirmed no design exists for "on for this module, off for that one." Whether this is worth building depends on item 3 above: it's only possible at all if the per-harness/per-provider overrides turn out to be independently addressable per session, which isn't yet confirmed.
8. **Graphify's git-hook refresh mechanism** (`graphify hook install/uninstall/status`): confirmed to exist (separate from the nudge hooks), but not yet verified in practice — whether post-commit/post-checkout rebuilds are fast enough to keep the graph usably fresh during an active session, and whether they fire correctly across the parallel git worktrees polly-pipe's implementors use (the staleness risk flagged when Graphify was first discussed).
9. **RTK's Bash-only hook limitation on Claude Code** (§9.6): the native hook only rewrites `Bash` tool calls — `Read`/`Grep`/`Glob` bypass it. If polly-pipe wants RTK's savings to actually apply, the orchestrator's prompt needs an explicit instruction to prefer `rtk read`/`rtk grep`/`rtk find` over those built-ins for Claude Code implementors specifically — confirm this instruction is both necessary and sufficient (i.e. that sub-agents reliably follow it) before assuming RTK delivers its claimed reduction in practice.
