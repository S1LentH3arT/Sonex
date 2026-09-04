"""Tests for the isolated memory filesystem transaction seam."""

from __future__ import annotations

import json

from src.memory.persistence import MemoryPersistence


def test_commit_and_recover_journaled_payloads(tmp_path) -> None:
    persistence = MemoryPersistence()
    destination = tmp_path / "state.json"
    journal = tmp_path / ".memory-transaction.json"

    persistence.commit({destination: '{"value": 1}\n'}, journal)

    assert json.loads(destination.read_text()) == {"value": 1}
    assert not journal.exists()


def test_recover_replays_staged_payload_and_rejects_corrupt_journal(tmp_path) -> None:
    persistence = MemoryPersistence()
    destination = tmp_path / "state.json"
    journal = tmp_path / ".memory-transaction.json"
    staged = tmp_path / ".state.json.pending.tmp"
    staged.write_text('{"value": 2}\n')
    journal.write_text(json.dumps({"version": 1, "staged": {str(destination): str(staged)}}))

    assert persistence.recover(journal)
    assert json.loads(destination.read_text()) == {"value": 2}
    assert not journal.exists()

    journal.write_text("{broken")
    assert not persistence.recover(journal)
