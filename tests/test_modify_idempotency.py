from __future__ import annotations

import json

from src.tools.modify_idempotency import (
    load_idempotency_entries,
    operation_fingerprint,
    record_idempotency_entry,
)


def test_operation_fingerprint_is_order_stable() -> None:
    assert operation_fingerprint([{"target": "up_next", "action": "clear"}]) == operation_fingerprint(
        [{"action": "clear", "target": "up_next"}]
    )


def test_idempotency_codec_round_trips_and_ignores_malformed_entries(tmp_path) -> None:
    path = tmp_path / "modify_idempotency.json"
    record_idempotency_entry(
        path,
        key="turn-1",
        fingerprint="abc",
        result={"status": "success"},
        completed_at=10,
    )
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"key": "turn-1", "fingerprint": "abc", "result": {"status": "success"}},
                    {"key": "invalid", "result": "not-a-dict"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_idempotency_entries(path) == {
        "turn-1": {
            "key": "turn-1",
            "fingerprint": "abc",
            "result": {"status": "success"},
        }
    }
