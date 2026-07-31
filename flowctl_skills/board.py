# Installable as part of the `flowctl_skills` package, on the same Python
# environment the orchestrator's claude-sdk executor runs in, so the dotted
# path `flowctl_skills.board.record_board_state` resolves via normal import
# (mirrors how omnigent's own guardrails reference
# omnigent.inner.nessie.policies.blast_radius).

import httpx

FLOWCTL_API = "http://localhost:7878"


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
    resp = httpx.post(f"{FLOWCTL_API}/api/tasks/{task_id}", json=payload, timeout=5)
    resp.raise_for_status()
    return {"ok": True}
