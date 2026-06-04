"""Smoke tests for the full-config local Muse runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_run_muse_full_local_refuses_empty_tables_dir(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_muse_full_local.sh"
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()

    env = os.environ.copy()
    env.update(
        {
            "MUSES_TABLE_DIR": str(tables_dir),
            "MUSES_FEEDBACK_DIR": str(tmp_path / "feedback"),
            "MUSES_SNAPSHOT_DIR": str(tmp_path / "snapshots"),
            "MUSES_BIND_HOST": "127.0.0.1",
            "MUSES_BIND_PORT": "8001",
        }
    )

    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "bootstrap_initial_cell.py" in result.stderr
    assert "no .jsonl tables" in result.stderr.lower()
