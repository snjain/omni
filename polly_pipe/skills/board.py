# Installable as part of the `polly_pipe` package, on the same Python
# environment the orchestrator's claude-sdk executor runs in, so the dotted
# path `polly_pipe.skills.board.record_board_state` resolves via normal
# import (mirrors how omnigent's own guardrails reference
# omnigent.inner.nessie.policies.blast_radius).
#
# Posts to icemetaagents' shared local API/dashboard server, not a
# polly-pipe-owned server - the platform routes this module's state to its
# own SQLite store at ~/.icemetaagents/modules/polly-pipe/board.db.

import httpx

ICEMETAAGENTS_API = "http://localhost:7878"
MODULE = "polly-pipe"


def record_board_state(
    task_id: str,
    status: str,
    implementor: str | None = None,
    reviewer: str | None = None,
    cost_usd: float | None = None,
    tokens: int | None = None,
    compression_saved_tokens: int | None = None,
    pr_url: str | None = None,
    dependencies: list[str] | None = None,
) -> dict:
    payload = {k: v for k, v in locals().items() if v is not None}
    resp = httpx.post(
        f"{ICEMETAAGENTS_API}/api/modules/{MODULE}/tasks/{task_id}",
        json=payload,
        timeout=5,
    )
    resp.raise_for_status()
    return {"ok": True}
