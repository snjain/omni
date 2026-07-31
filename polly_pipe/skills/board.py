# Installable as part of the `polly_pipe` package, on the same Python
# environment the orchestrator's claude-sdk executor runs in, so the dotted
# path `polly_pipe.skills.board.record_board_state` resolves via normal
# import (mirrors how omnigent's own guardrails reference
# omnigent.inner.nessie.policies.blast_radius).
#
# Writes directly to this module's own SQLite database - no local API/state
# server sits in front of it. record_board_state is the sole writer, so
# there's no concurrent-write hazard to mediate; the TUI/web dashboard open
# the same file read-only and poll it (see PRD §11, §14). WAL mode is set on
# first connection so those readers don't block on this writer (PRD §16).

import json
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".iceagentkit" / "modules" / "polly-pipe" / "board.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    implementor TEXT,
    reviewer TEXT,
    cost_usd REAL,
    tokens INTEGER,
    compression_saved_tokens INTEGER,
    pr_url TEXT,
    dependencies TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_SCHEMA)
    return conn


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
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tasks (task_id, status, implementor, reviewer, cost_usd,
                                tokens, compression_saved_tokens, pr_url, dependencies,
                                updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(task_id) DO UPDATE SET
                status = excluded.status,
                implementor = COALESCE(excluded.implementor, implementor),
                reviewer = COALESCE(excluded.reviewer, reviewer),
                cost_usd = COALESCE(excluded.cost_usd, cost_usd),
                tokens = COALESCE(excluded.tokens, tokens),
                compression_saved_tokens = COALESCE(excluded.compression_saved_tokens, compression_saved_tokens),
                pr_url = COALESCE(excluded.pr_url, pr_url),
                dependencies = COALESCE(excluded.dependencies, dependencies),
                updated_at = datetime('now')
            """,
            (
                task_id,
                status,
                implementor,
                reviewer,
                cost_usd,
                tokens,
                compression_saved_tokens,
                pr_url,
                json.dumps(dependencies) if dependencies is not None else None,
            ),
        )
    return {"ok": True}
