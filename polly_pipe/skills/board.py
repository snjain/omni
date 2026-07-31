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
#
# Path resolution follows PRD §11.3 / §11.4: XDG on Linux AND macOS (matching
# Omnigent's own convention - install_ledger.py, update_check.py, and its
# onboarding modules all honor XDG_* on any OS rather than switching to
# Apple's ~/Library/Application Support on macOS), %LOCALAPPDATA% on Windows.
# Deliberately not using platformdirs' default macOS behavior, which would
# diverge from that.

import json
import os
import sqlite3
import sys
from pathlib import Path


def _iceagentkit_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "iceagentkit" / "data"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "iceagentkit"


DB_PATH = _iceagentkit_data_dir() / "modules" / "polly-pipe" / "board.db"

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
