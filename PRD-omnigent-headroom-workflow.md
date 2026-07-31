# PRD: Plan-to-PR Agentic Workflow on Omnigent + Headroom

## 1. Summary

A workflow layer built on top of **Omnigent** (multi-agent session harness with sandboxing, spend policies, and model routing) and **Headroom** (lossless context-compression middleware). Users describe a goal in freeform text; an agent turns it into a detailed plan through human-reviewed iteration; once approved, the plan is decomposed into a dependency-aware task board where each task is implemented and reviewed by AI models (assigned via Omnigent's router), with humans gating the two points where real work/spend begins: plan finalization and task-board finalization ("the paid turn"). Every agent session involved runs through Headroom's compression layer to control token cost and context-window usage.

## 2. Goals

- Turn a freeform requirement into a reviewed, human-approved implementation plan.
- Decompose the approved plan into a task board of discrete, dependency-linked tasks.
- Auto-assign an implementor model and a reviewer model per task via Omnigent's model router, based on task complexity signals.
- Execute tasks (parallel where dependencies allow) producing one PR per task, with AI review before human escalation on failure.
- Give humans visibility and control: cost, tokens, compression savings, status, and dependencies per task; ability to run step-by-step or continuously.
- Route all agent-session traffic through Headroom so cost/context benefits apply everywhere, not just at execution.

## 3. Non-Goals / Out of Scope

- Concrete complexity-scoring algorithm/weights (signals are named; scoring rubric is left to Omnigent's own `sys_advise_models` recommendation, see §10).
- UI mockups / wireframes (a separate design artifact, not this PRD).
- Detailed sequence diagrams beyond the architecture diagram in §11.

## 4. Actors

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

## 5. Workflow

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
- Each Implementor runs inside an Omnigent agent session, with all model traffic wrapped by Headroom's compression layer.
- On completion, the Implementor opens **one PR per task**. Humans always merge; agents never do (confirmed convention, see §9.3).
- The task's Reviewer model reviews the PR:
  - **Approved** → task status = Done.
  - **Rejected** → task status = Rejected-Needs-Human, **escalated to a human** — no automatic retry.
- The board updates live: status, cost, tokens, compression savings, PR link.

## 6. Task Board — Data Model

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

## 8. Assumptions

- Omnigent and Headroom are used as-is (third-party products); this workflow is a layer built on top, not a fork/modification of either.
- Omnigent's `sys_advise_models` is the mechanism used for per-task model assignment — this workflow supplies the complexity signals, Omnigent's router makes the assignment.
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

### 9.2 Headroom ↔ Omnigent wiring (resolved, with a correction)

Neither product's docs mention the other by name, but the mechanism to connect them is real and documented on each side independently:

- **Omnigent's Gateway** accepts "any OpenAI- or Anthropic-compatible `base_url` and key" (examples given: OpenRouter, Ollama). Configured via `omnigent setup`.
- **Headroom's proxy mode** (`headroom proxy --port 8787`) serves both Anthropic `/v1/messages` and OpenAI-compatible `/v1/chat/completions`/`/v1/responses` routes locally, compressing transparently before forwarding to the real provider.

**Wiring**: point Omnigent's `base_url` override(s) at `http://localhost:8787` (Headroom's proxy). Every model call routed through it gets compressed before reaching the real provider.

**Correction — this is likely not one unified knob.** Earlier drafts of this PRD described a single "Gateway `base_url`" setting. Searching Omnigent's source shows separate, narrower overrides instead: general provider vars (`ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`) plus per-harness gateway vars (`HARNESS_PI_GATEWAY_BASE_URL`, `HARNESS_QWEN_GATEWAY_BASE_URL`, and presumably others per harness). Whether `omnigent setup` unifies these into one config entry for you, or you'd need to set several independently, is **not yet confirmed** — flag as a §16 item: enumerate the full set of base_url-style knobs before implementation.

**Unverified assumption (needs a PoC before relying on it, see §16)**: whether Omnigent's Gateway sits in the request path for *every* harness session (Claude Code, Cursor, OpenCode, etc.) or only for Omnigent's own built-in/custom agents. If it's the latter, only the orchestrator's own "brain" calls get compressed, not the sub-agent harnesses' calls.

**Design decision — flowctl presents one global switch regardless.** Even though the underlying knobs may be per-provider/per-harness, flowctl deliberately does not expose that granularity to the user. `flowctl compression on` / `flowctl compression off` sets or unsets *every* known base_url override together, so compression is a single on/off decision from the user's point of view — see §13. The risk this creates: if a new harness's gateway var isn't in flowctl's known list, toggling "off" could leave that one harness still routed through Headroom, silently breaking the "global switch" promise. §16 needs an explicit, versioned list of every override flowctl must touch, kept in sync as Omnigent adds harnesses.

### 9.3 Distribution & licensing

| | Headroom | Omnigent |
|---|---|---|
| Distribution | `pip install "headroom-ai[all]"` | `curl -fsSL https://omnigent.ai/install.sh \| sh` or `uv tool install omnigent` |
| License | Apache 2.0, open source | Apache 2.0, open source |
| Repo | github.com (search `headroom-ai`) | `omnigent-ai/omnigent` |

Both Apache 2.0 → bundling/redistribution is legally permitted; must retain each project's `LICENSE`/`NOTICE` and mark any modifications. No requirement to open-source flowctl's own code.

**PR merge convention (confirmed via `examples/polly/config.yaml`)**: implementer sub-agents always open their own PR and never merge; the human merges. flowctl adopts this as-is — no auto-merge.

### 9.4 Omnigent's session storage (`chat.db`) — and why flowctl doesn't write into it

Confirmed directly in `omnigent-ai/omnigent`'s source (`docs/omni-upgrade-design.md`): *"All durable state lives in sqlite (`~/.omnigent/chat.db`), not in [the server/daemon] — server/daemon [is] safe to stop and respawn; they rehydrate from sqlite."* Locally this defaults to `~/.omnigent/chat.db`; hosted deployments (Fly, Render, HF Spaces, Cloudflare) can point `DATABASE_URL`/`--database-uri` at Postgres instead, since SQLite doesn't hold up under concurrent multi-instance access (Modal's own docs explicitly rule out a SQLite tier for that reason).

`chat.db` holds more than literal chat messages — sessions, conversations, agents, files, policies, permissions, comments, and scheduled tasks each have their own store module (`omnigent/stores/{agent,artifact,comment,conversation,file,permission,policy,project,scheduled_task}_store`), all backed by the same SQLite file by default.

**Checked whether flowctl could add its own `board` table into `chat.db` — no sanctioned way to do that:**
- `omnigent/stores/` is a **fixed, closed list** of store modules, not a plugin registry.
- Searched the repo for `"custom store"` and `register_store` — zero matches. No hook exists for registering a new store/table.
- The schema is Alembic-migration-managed by Omnigent's own release process (`omnigent/db/migrations/versions/...`); an externally-added table would sit outside that history, with no compatibility guarantee across Omnigent upgrades, and risks lock contention with Omnigent's own server process as a second uncoordinated writer.

**Decision: flowctl maintains its own separate SQLite database, `~/.flowctl/board.db`**, fully owned and schema-controlled by flowctl, independent of Omnigent's release cycle:
- Only flowctl's local API server (`:7878`, see §11) reads/writes `board.db` directly — `record_board_state` never touches the file itself, it POSTs to that API, keeping DB access single-writer.
- The web/TUI dashboards read from the same API server, not the file directly — one source of truth for board-specific data.
- Optional, read-only correlation: the API server may separately open `~/.omnigent/chat.db` **read-only** to pull session/conversation metadata by `session_id`/`conversation_id` for display alongside a task — never as a write target.

## 10. Omnigent Extensibility Model

Checked directly against the `omnigent-ai/omnigent` codebase (not inferred): **there is no plugin, hook, extension, or middleware system** — searched the repo for all four terms, zero matches. The only two extension surfaces are:

1. **Custom agents** — a YAML file (`spec_version`, `name`, `prompt`, `executor`, `tools`, `guardrails`, ...) invoked via `omnigent run path/to/config.yaml`. No alias/registry exists; there's no way to invoke a custom agent as a short top-level command like a built-in harness.
2. **The Gateway config** — the `base_url`/key override described in §9.2, the only way to intercept/redirect model traffic.

Within a custom agent, two categories of extension are easy to conflate — they are **not** the same thing:

| | Skills | Function tools |
|---|---|---|
| What it is | **Prose** (`SKILL.md`), loaded via the `Skill` tool mid-conversation | Real Python, referenced by dotted import path |
| Where it lives | `<agent-dir>/skills/<name>/SKILL.md` — never the host `~/.claude/skills/` | An installed, importable Python package (e.g. `pip install -e .`) on the same environment the agent's executor runs in; referenced as `callable: flowctl_skills.board.record_board_state` in the YAML `tools:` block |
| Confirmed by | Polly's own config: *"skills are prose, not code... A skill always belongs in polly's OWN skills directory"* | Polly's guardrails reference `path: omnigent.inner.nessie.policies.blast_radius` — a plain dotted import path |
| Used for | Reusable instruction modules (Polly has `investigate`, `fanout`, `cross-review`) | Anything that must reliably *do* something outside the model's own reasoning — flowctl's only use case is `record_board_state` |

**Sessions are interactive/multi-turn**, not one-shot/headless — confirmed. This is why the PRD's human-approval gates (plan, board, paid-turn) don't need a separate polling/blocking mechanism: the orchestrator's `prompt` just says "present X, then wait for the human's reply," and the session naturally blocks there.

### 10.1 Adding more agents going forward

Two paths, both confirmed against real Omnigent config structure:

- **Static roster member** (a permanent, named, roster-preflighted sub-agent role): add `agents/<name>/config.yaml` (same schema as the orchestrator itself — see `examples/polly/agents/claude_code/config.yaml` and `.../pi/config.yaml`, which are nearly identical aside from `executor.config.harness`), add `<name>` to `tools.agents` in the orchestrator's YAML, extend the roster-preflight check and `guardrails.policies` as needed.
- **Dynamic/ad-hoc agent** (a one-off, narrowly-scoped helper): set `spawn: true` on the orchestrator (already in the template in this repo) — this registers `sys_session_create`, which lets the orchestrator author a brand-new agent config at runtime and launch it via `config_path`, with **no static YAML change required**. Recommended default for anything not part of the fixed roster.

## 11. Final Architecture — Hybrid Design

All orchestration logic (plan, decompose, dispatch, cross-model review, PR creation, all three approval gates) lives **inside Omnigent** as one custom agent, invoked purely via `omnigent run`. flowctl is deliberately thin — it exists only for the one thing Omnigent structurally cannot host: a live, structured, multi-column dashboard (Omnigent's UI has no extension point, confirmed in §10).

```
                         ┌─────────────────────────────────────────┐
                         │            YOU (human)                   │
                         │  talks to orchestrator · watches board    │
                         └───────────┬───────────────┬───────────────┘
                                     │               │
                     interactive session          reads/watches
                     (plan review, board                │
                      approval, paid-turn,               ▼
                      rejection escalation)     ┌──────────────────────┐
                                     │           │  flowctl dashboard    │
                                     ▼           │  (web + TUI renderers)│
                    ┌────────────────────────┐   └──────────┬────────────┘
                    │   omnigent run          │              │ SSE/WebSocket
                    │   orchestrator/config.yaml│              │
                    │   (custom agent, forked  │   ┌──────────▼────────────┐
                    │    from Polly's pattern) │   │  flowctl local API /   │
                    │                          │──▶│  state store           │
                    │  record_board_state()    │   │  (localhost:7878)      │
                    │  called after every       │   └────────────────────────┘
                    │  dispatch/review/PR/cost   │
                    └───────────┬────────────────┘
                                │ dispatches sub-agents into
                                │ parallel git worktrees
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
                    │   Gateway: base_url override    │
                    └───────────┬────────────────────┘
                                │ Gateway base_url points here
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

| Component | What it is | Built by flowctl? |
|---|---|---|
| Headroom | Third-party pip package, proxy on :8787 | No |
| Omnigent | Third-party meta-harness | No |
| Harnesses (Claude Code, Codex, Cursor, OpenCode, Pi, Hermes) | Third-party coding agents | No |
| Orchestrator agent (`config.yaml` + skills) | Custom Omnigent agent, forked from `examples/polly` | **Yes** — see `flowctl-orchestrator-config.yaml` in this repo |
| flowctl local API / state store | Small server on :7878, backed by its own SQLite (`~/.flowctl/board.db`) — separate from Omnigent's `~/.omnigent/chat.db`, see §9.4 | **Yes** |
| flowctl dashboard (web + TUI) | Render layers on the state API | **Yes** |
| flowctl installer/setup | Install + wiring script | **Yes** |
| GitHub | External | No |

## 12. Implementation Files (in this repo)

- **`flowctl-orchestrator-config.yaml`** — the orchestrator agent template: five-phase prompt (plan → decompose → board review → paid-turn → execute), `spawn: true` for dynamic sub-agents, `record_board_state` function-tool wiring, guardrails (`blast_radius`, `spawn_bounds`, `headless_subagent_purpose_guard`) reused from Omnigent's own reference orchestrator. Placeholders marked `[Reuse polly's proven prose verbatim for: ...]` should be filled by copying the matching sections from `examples/polly/config.yaml` in the `omnigent-ai/omnigent` repo rather than re-deriving them.
- **`flowctl_skills/board.py`** — the one real Python function tool (`record_board_state`), posting task state to flowctl's local API. This is the only custom code referenced from the orchestrator's `tools:` block; everything else in the YAML is prose.
- Sub-agent configs (`claude_code`, `codex`, `opencode`, `cursor`, `hermes`, `pi`) need **no changes** from Omnigent's own `examples/polly/agents/<name>/config.yaml` — board reporting is orchestrator-side only.

## 13. Installation & CLI UX

```bash
curl -fsSL https://flowctl.dev/install.sh | sh    # pip-installs headroom-ai,
                                                     # installs omnigent, registers
                                                     # the orchestrator agent

flowctl setup    # collects provider/GitHub keys, spend caps, concurrency limit;
                  # starts Headroom proxy; points Omnigent Gateway at it;
                  # starts the flowctl state/dashboard server

flowctl doctor   # fires a dummy session through Omnigent and confirms Headroom's
                  # proxy actually saw and compressed the traffic — the built-in
                  # version of the §16 PoC, so it's checkable on every install,
                  # not just once during design
```

Day-to-day, the actual plan/board/execution interaction happens **inside the interactive `omnigent run` session** (conversational, per §10) — flowctl does not reimplement `plan new`/`board create` as separate CLI business logic. flowctl's own CLI surface is just:

```bash
flowctl start        # shorthand for: omnigent run ~/.flowctl/agents/orchestrator/config.yaml
flowctl board         # opens the dashboard — TUI by default (terminal-native, matches
                        # Omnigent's own posture); `--web` opens the browser version instead

flowctl compression off   # unsets every known base_url override (ANTHROPIC_BASE_URL,
                            # OPENAI_BASE_URL, HARNESS_PI_GATEWAY_BASE_URL, etc. — see §9.2)
                            # so both plain `omnigent` and flowctl talk to the real
                            # provider directly. One switch, regardless of how many
                            # underlying knobs exist.
flowctl compression on    # re-applies them, pointed at the Headroom proxy
flowctl compression status   # reports which known overrides are currently set vs. unset —
                               # surfaces drift instead of silently trusting the last toggle
```

**Deliberately a single global switch, not per-harness controls** — flowctl always sets/unsets the full known list together (§9.2), even though Omnigent's underlying mechanism is more granular. `status` exists specifically to catch the failure mode where a new harness's override isn't in flowctl's known list yet and gets missed by a toggle.

## 14. Dashboard: Web + TUI

Both are thin render layers on the same flowctl state API (§11) — no duplicated bridge logic. Recommended library for the TUI: **Textual** (Python, matches the rest of the stack, handles live-updating multi-column tables well). Tradeoff to keep in mind: Omnigent's own selling point is session continuity across terminal → browser → phone; a TUI-first board doesn't carry over to mobile the way the web version does, so the web dashboard is the one that has to exist if "check the board from my phone" matters — TUI is additive, not a replacement.

## 15. Cost/Token/Compression Reporting

Sourced by the orchestrator from each sub-agent dispatch's result and included in the `record_board_state` call: `cost_usd`, `tokens` (raw), `compression_saved_tokens` (from Headroom, if the provider response surfaces it). Shown per-task on the board, not just aggregated at the plan level, per the original brief.

## 16. Remaining Unverified Assumptions — Do These Before Committing Further

1. **Gateway request-path scope** (§9.2): confirm Omnigent's Gateway/base_url overrides actually intercept *every* harness's model calls, not just the orchestrator's own. Test: point the override(s) at a dummy logging server, dispatch a Cursor- or Claude-Code-orchestrated sub-agent task, confirm the dummy server sees it.
2. **`omnigent setup`'s config format**: inspect what it actually writes (e.g. `~/.omnigent/...`) so the installer can pre-populate/patch it programmatically rather than requiring interactive input.
3. **Full enumeration of base_url-style overrides** (§9.2): confirmed so far — `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `HARNESS_PI_GATEWAY_BASE_URL`, `HARNESS_QWEN_GATEWAY_BASE_URL`. Unconfirmed — whether every other harness (Claude Code, Codex, Cursor, OpenCode, Hermes, Antigravity) has its own equivalent, and whether `omnigent setup` exposes one unified entry point for all of them or each must be set independently. This list is exactly what `flowctl compression on/off` needs to stay complete and correct — treat it as a living list, re-verified whenever Omnigent adds a harness.
4. **Cost/token/compression-saving surfacing**: confirm what Omnigent's dispatch results (or Headroom's own stats endpoint) actually expose per-call, since `record_board_state`'s `cost_usd`/`tokens`/`compression_saved_tokens` fields depend on this being real, retrievable data.
