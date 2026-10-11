"""Focused tests for the read-only snapshot scoring helper."""

from __future__ import annotations

import hashlib
from pathlib import Path

from birkin_mnemosyne import consolidation
from birkin_mnemosyne.consolidation import questions_from_snapshots


def snapshot(path: str, body: str, title: str = "note") -> consolidation.NoteSnapshot:
    return consolidation.NoteSnapshot(
        path, title, hashlib.sha256(body.encode("utf-8")).hexdigest(), body, ())


def test_equal_basename_nested_paths_remain_distinct():
    body = "alpha bravo charlie delta echo"
    notes = [snapshot("memory/policy.md", body),
             snapshot("archive/policy.md", body)]
    questions = questions_from_snapshots(notes, 20)
    assert len(questions) == 1
    question, = questions
    assert question.first.path != question.second.path
    assert {Path(question.first.path).name,
            Path(question.second.path).name} == {"policy.md"}
    assert question.reason == "duplicate"


def test_duplicate_and_overlap_use_existing_ids_and_reasons():
    a = snapshot("m/a.md", "alpha bravo charlie delta")
    b = snapshot("m/b.md", "alpha bravo charlie delta")
    c = snapshot("m/c.md", "alpha bravo charlie echo")
    questions = questions_from_snapshots([a, b, c], 20)
    reasons = {(q.first.path, q.second.path): q.reason for q in questions}
    assert reasons == {
        ("m/a.md", "m/b.md"): "duplicate",
        ("m/a.md", "m/c.md"): "overlap-or-conflict",
        ("m/b.md", "m/c.md"): "overlap-or-conflict",
    }
    for question in questions:
        assert question.id == consolidation._question_id(
            question.first, question.second)


def test_input_order_does_not_change_result():
    notes = [
        snapshot("m/a.md", "alpha bravo charlie delta"),
        snapshot("m/b.md", "alpha bravo charlie delta"),
        snapshot("m/c.md", "alpha bravo charlie echo"),
        snapshot("m/d.md", "alpha bravo charlie foxtrot"),
    ]
    ordered = [q.id for q in questions_from_snapshots(notes, 20)]
    assert ordered
    assert [q.id for q in questions_from_snapshots(list(reversed(notes)), 20)] \
        == ordered
    assert [q.id for q in questions_from_snapshots([notes[2], notes[0],
                                                    notes[3], notes[1]], 20)] \
        == ordered


def test_nonpositive_limit_yields_no_questions():
    notes = [snapshot("m/a.md", "alpha bravo charlie delta"),
             snapshot("m/b.md", "alpha bravo charlie delta")]
    assert questions_from_snapshots(notes, 0) == ()
    assert questions_from_snapshots(notes, -3) == ()
    assert len(questions_from_snapshots(notes, 1)) == 1


def test_scoring_helper_writes_nothing_to_disk(tmp_path):
    vault = tmp_path / "vault"
    (vault / "m").mkdir(parents=True)
    bodies = {"m/a.md": "alpha bravo charlie delta",
              "m/b.md": "alpha bravo charlie delta"}
    notes = []
    for rel, body in bodies.items():
        path = vault / rel
        path.write_text(body, encoding="utf-8")
        notes.append(snapshot(rel, body))

    def fingerprint():
        return {p.relative_to(vault).as_posix(): (p.read_bytes(),
                 p.stat().st_mtime_ns) for p in vault.rglob("*") if p.is_file()}

    before = fingerprint()
    assert questions_from_snapshots(notes, 20)
    assert fingerprint() == before
