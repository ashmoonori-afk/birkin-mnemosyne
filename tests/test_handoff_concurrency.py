"""Two fresh processes race the same immutable checkpoint through the API."""

from __future__ import annotations

import multiprocessing
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

from birkin_mnemosyne.handoff_records import HandoffFields, HandoffScope
from birkin_mnemosyne.handoffs import HandoffStore


def _capture_together(
    vault: str, start: Barrier, results: Queue[tuple[bool, str, str]],
) -> None:
    store = HandoffStore(vault)
    scope, fields = HandoffScope("shared-project", "same-task"), HandoffFields("same checkpoint")
    _ = start.wait(timeout=30)
    receipt = store.capture(scope, fields, capture_id="same-event")
    results.put((receipt.created, receipt.path, receipt.sha256))


def test_simultaneous_processes_publish_one_checkpoint(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(3)
    results: Queue[tuple[bool, str, str]] = context.Queue()
    workers = [
        context.Process(target=_capture_together, args=(str(tmp_path), start, results))
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        # Both children signal readiness through the same barrier before any
        # capture is released. There is no timing delay or polling loop.
        _ = start.wait(timeout=30)
        receipts = [results.get(timeout=30), results.get(timeout=30)]
        for worker in workers:
            worker.join(timeout=30)
            assert worker.exitcode == 0
        assert sorted(receipt[0] for receipt in receipts) == [False, True]
        assert receipts[0][1:] == receipts[1][1:]
        notes = HandoffStore(tmp_path).records(HandoffScope("shared-project", "same-task"))
        assert len(notes) == 1 and notes[0].sha256 == receipts[0][2]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=10)
        results.close()
        results.join_thread()
