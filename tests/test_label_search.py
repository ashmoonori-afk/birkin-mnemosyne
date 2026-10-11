"""Label filtering on indexed search: AND eligibility before any candidate cut.

The cache stores the actual note labels (``_note_entry`` -> ``labels``) under
an incremented ``INDEX_VERSION`` that rebuilds stale caches through the
existing contract. ``Mnemosyne.search(..., labels=...)`` restricts candidate
eligibility to notes that carry every requested label, without changing any
score, IDF, doclen or ranking when filters are missing or empty. Malformed
requests raise before any lookup and never broaden; malformed on-disk label
metadata never breaks unfiltered recall and never matches a filter.
"""

from __future__ import annotations

import json
import zlib
from datetime import datetime, timezone

import pytest

from birkin_mnemosyne import mnemosyne
from birkin_mnemosyne.label_values import LabelError

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)

# -- helpers ----------------------------------------------------------------


def _write(vault, slug: str, body: str, *,
           labels: tuple[str, ...] | None = None) -> None:
    """Write one real note file. labels=None writes no labels field; an
    explicit tuple (including ()) writes the field with those values."""
    header = [f"title: {slug}"]
    if labels is not None:
        header.append(f"labels: {json.dumps(list(labels))}")
    (vault / f"{slug}.md").write_text(
        "---\n" + "\n".join(header) + "\n---\n\n" + body + "\n",
        encoding="utf-8")


# -- eligibility before the candidate cut -----------------------------------

def test_label_filter_returns_a_note_beyond_the_unfiltered_top32(tmp_path):
    # Given: 40 notes all holding the query term "alpha"; the target note
    # carries the most filler terms, so the longest doclen ranks it 40th,
    # beyond the CAND=32 candidate cut of an unfiltered search.
    for i in range(40):
        slug = f"note{i:02d}"
        labels = ("project:needle",) if i == 39 else ("project:other",)
        filler = " ".join(f"w{j:02d}" for j in range(5 * (i + 1)))
        _write(tmp_path, slug, f"alpha {filler}", labels=labels)
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: the same query is searched with the target's label filter.
    unfiltered = [h["slug"] for h in dex.search("alpha", limit=100)]
    hits = dex.search("alpha", limit=100, labels=["project:needle"])

    # Then: the note is unreachable unfiltered, and the filter returns it —
    # alone, because every other note is ineligible before the top-k cut.
    assert "note39" not in unfiltered
    assert len(unfiltered) <= 32
    assert [h["slug"] for h in hits] == ["note39"]


def test_multiple_labels_are_and(tmp_path):
    # Given: notes carrying one or both of the requested labels.
    _write(tmp_path, "both", "shared keyword", labels=("project:alpha", "lang:ko"))
    _write(tmp_path, "one", "shared keyword", labels=("project:alpha",))
    _write(tmp_path, "other", "shared keyword", labels=("lang:ko",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: single-label and two-label filters are searched.
    by_project = {h["slug"] for h in
                  dex.search("shared keyword", labels=["project:alpha"])}
    by_lang = {h["slug"] for h in
               dex.search("shared keyword", labels=["lang:ko"])}
    by_both = [h["slug"] for h in dex.search(
        "shared keyword", labels=["project:alpha", "lang:ko"])]

    # Then: each label selects its notes and the pair intersects (AND).
    assert by_project == {"both", "one"}
    assert by_lang == {"both", "other"}
    assert by_both == ["both"]


def test_project_label_values_stay_distinct(tmp_path):
    # Given: two notes whose only difference is the value spelling.
    _write(tmp_path, "lower", "unique term zebra", labels=("project:alpha",))
    _write(tmp_path, "upper", "unique term zebra", labels=("project:Alpha",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: filters vary namespace case and value case.
    lower = [h["slug"] for h in dex.search("zebra", labels=["project:alpha"])]
    upper = [h["slug"] for h in dex.search("zebra", labels=["project:Alpha"])]
    folded = [h["slug"] for h in dex.search("zebra", labels=["PROJECT:alpha"])]

    # Then: values are never conflated; only the namespace case folds.
    assert lower == ["lower"]
    assert upper == ["upper"]
    assert folded == ["lower"]


def test_missing_empty_and_covering_filters_keep_scores_and_order(tmp_path):
    # Given: three notes ranked best/mid/weak by term frequency, all labeled.
    _write(tmp_path, "best", "alpha alpha alpha shared",
           labels=("project:x", "lang:en"))
    _write(tmp_path, "mid", "alpha alpha shared",
           labels=("project:y", "lang:en"))
    _write(tmp_path, "weak", "alpha shared", labels=("lang:en",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: filters are missing, empty, or select every note.
    baseline = dex.search("alpha", limit=10, now=NOW)
    assert [h["slug"] for h in baseline] == ["best", "mid", "weak"]
    none_filter = dex.search("alpha", limit=10, labels=None, now=NOW)
    empty_list = dex.search("alpha", limit=10, labels=[], now=NOW)
    empty_tuple = dex.search("alpha", limit=10, labels=(), now=NOW)
    covering = dex.search("alpha", limit=10, labels=["lang:en"], now=NOW)

    # Then: score/rank sequences are byte-identical to the unfiltered run.
    assert [h["slug"] for h in none_filter] == ["best", "mid", "weak"]
    assert none_filter == baseline
    assert empty_list == baseline
    assert empty_tuple == baseline
    assert covering == baseline


def test_labels_are_stored_but_never_feed_terms_or_doclen(tmp_path):
    # Given: two identical notes, one carrying a label whose value is a word
    # absent from every body.
    _write(tmp_path, "tx", "plain body", labels=("project:needle",))
    _write(tmp_path, "px", "plain body")
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: the label value is queried and metadata is compared.
    needle_hits = dex.search("needle")
    tagged = dex.note_meta("tx")
    plain = dex.note_meta("px")
    assert tagged is not None and plain is not None

    # Then: labels are stored as actual metadata, are never tokenized into
    # the index, and add nothing to doclen.
    assert tagged["labels"] == ["project:needle"]
    assert plain["labels"] == []
    assert needle_hits == []
    assert tagged["doclen"] == plain["doclen"]
    assert plain["doclen"] == mnemosyne._doc_length(
        {t: 1 for t in mnemosyne.tokenize("px plain body")})


def test_explicit_empty_labels_are_stored_and_never_match(tmp_path):
    # Given: an explicitly empty labels field next to a labeled note.
    _write(tmp_path, "empty", "alpha body", labels=())
    _write(tmp_path, "tagged", "alpha body", labels=("project:x",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: metadata is read and label filters are applied.
    # Then: the empty field survives as (), excludes nothing unfiltered, and
    # never satisfies a positive filter.
    empty = dex.note_meta("empty")
    assert empty is not None
    assert empty["labels"] == []
    assert {h["slug"] for h in dex.search("alpha")} == {"empty", "tagged"}
    assert [h["slug"] for h in dex.search("alpha", labels=["project:x"])] == ["tagged"]
    assert dex.search("alpha", labels=["project:y"]) == []


# -- cache schema and rebuild ------------------------------------------------

def test_old_cache_without_label_metadata_is_rebuilt(tmp_path):
    # Given: a fresh note whose on-disk cache was written by the previous
    # schema (INDEX_VERSION - 1, entries without the labels key), with a
    # fingerprint that matches the file so only the version guard can force
    # the re-parse.
    _write(tmp_path, "note", "shared alpha", labels=("project:kept",))
    st = (tmp_path / "note.md").stat()
    stale = {"version": mnemosyne.INDEX_VERSION - 1, "notes": {"note": {
        "title": "note", "rel": "note.md", "zone": "", "type": "topic",
        "tags": [], "links": [], "created": "", "updated": "",
        "confidence": 0.5, "polarity": "positive", "expires_at": None,
        "summary": "", "mtime": st.st_mtime, "size": st.st_size,
        "doclen": 2, "terms": {"shared": 1, "alpha": 1}}}}
    (tmp_path / mnemosyne.INDEX_FILE).write_bytes(
        zlib.compress(json.dumps(stale).encode()))

    # When: a label-filtered search touches the stale cache.
    dex = mnemosyne.Mnemosyne(tmp_path)
    hits = [h["slug"] for h in dex.search("alpha", labels=["project:kept"])]

    # Then: the version mismatch rebuilds the cache, labels survive the
    # rebuild, and the refreshed file carries the new schema version.
    assert hits == ["note"]
    refreshed = json.loads(zlib.decompress(
        (tmp_path / mnemosyne.INDEX_FILE).read_bytes()))
    assert refreshed["version"] == mnemosyne.INDEX_VERSION
    assert refreshed["notes"]["note"]["labels"] == ["project:kept"]
    assert mnemosyne._decode_index(
        zlib.compress(json.dumps(refreshed, separators=(",", ":")).encode())
    ) == dex.entries()


# -- hybrid and expanded cuts -------------------------------------------------

class _SliceSemantic:
    """Faithful stand-in for the semantic engine: ranks every synced note
    and slices to the limit exactly like the real ``search`` would, so a
    note beyond FUSE_DEPTH requires a wider search before filtering."""

    def __init__(self) -> None:
        self.synced: dict[str, dict[str, object]] = {}

    def sync(self, entries: dict[str, dict[str, object]]) -> None:
        self.synced = dict(entries)

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        ranked = sorted((
            (s, float(len(self.synced) - i))
            for i, (s, _) in enumerate(sorted(self.synced))),
            key=lambda kv: kv[1], reverse=True)
        return ranked[:limit]


def test_label_filter_reaches_a_note_beyond_both_fusion_cuts(tmp_path, monkeypatch):
    # Given: 151 notes all holding "alpha"; the target's longest body ranks
    # it beyond FUSE_DEPTH in both the lexical and semantic legs of an
    # unfiltered fused search, and the fake engine slices like the real one.
    for i in range(150):
        filler = " ".join(f"w{n:03d}" for n in range(2 * (i + 1)))
        _write(tmp_path, f"f{i:03d}", f"alpha {filler}",
               labels=("project:other",))
    target_filler = " ".join(f"t{n:03d}" for n in range(400))
    _write(tmp_path, "target", f"alpha {target_filler}",
           labels=("project:goal",))
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=True)
    fake = _SliceSemantic()
    monkeypatch.setattr(dex, "_semantic_index", lambda: fake)

    # When: the query runs unfiltered and then only on the target's label.
    unfiltered = [h["slug"] for h in dex.search("alpha", limit=100)]
    filtered = [h["slug"] for h in dex.search(
        "alpha", limit=100, labels=["project:goal"])]

    # Then: the target is unreachable through either unfiltered leg, while the
    # filtered run preserves the corpus while requesting enough semantic
    # candidates to apply eligibility before the fusion cut.
    assert "target" not in unfiltered
    assert set(fake.synced) == {*(f"f{i:03d}" for i in range(150)), "target"}
    assert filtered == ["target"]


def test_label_filter_keeps_a_full_match_beyond_the_cut_pinned(tmp_path):
    # Given: filler notes and a target all holding every unit of the query
    # plus the expansion term; the target's longest body ranks it beyond
    # FUSE_DEPTH (the covering slice) and the CAND cut of an unfiltered
    # expansion search.
    for i in range(110):
        filler = " ".join(f"q{n:03d}" for n in range(2 * (i + 1)))
        _write(tmp_path, f"f{i:03d}", f"alpha beta gamma {filler}",
               labels=("project:other",))
    target_filler = " ".join(f"t{n:03d}" for n in range(300))
    _write(tmp_path, "target", f"alpha beta gamma {target_filler}",
           labels=("project:goal",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: the full-match target is the only eligible note, searched with
    # and without an expansion that the target's body also holds.
    core = dex.search("alpha beta", labels=["project:goal"], now=NOW)[0]
    expanded = dex.search("alpha beta", labels=["project:goal"], now=NOW,
                          expansions={"synonyms": ["gamma"]})[0]
    unfiltered = [h["slug"] for h in dex.search("alpha beta", limit=100)]

    # Then: the covering full match keeps its core score (no expansion
    # boost), stays pinned, and is unreachable without the label filter.
    assert "target" not in unfiltered
    assert core["slug"] == "target" == expanded["slug"]
    assert expanded["score"] == core["score"]


# -- malformed input ---------------------------------------------------------

@pytest.mark.parametrize("bad", [
    ["no-colon"],
    ["ns:"],
    ["ns: "],
    ["-bad:value"],
    ["ns:ok", "broken"],
    ["ns:v\x00control"],
], ids=["no-colon", "empty-value", "blank-value",
        "bad-namespace", "second-entry-bad", "control-char"])
def test_malformed_label_filters_are_refused_before_lookup(tmp_path, bad):
    _write(tmp_path, "note", "alpha body", labels=("project:fine",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    with pytest.raises(LabelError):
        dex.search("alpha", labels=bad)


def test_a_string_label_filter_is_refused_not_broadened(tmp_path):
    # Given: a note that would match if the string were treated as one label.
    _write(tmp_path, "note", "alpha body", labels=("project:fine",))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: a bare string is passed where an iterable of labels belongs.
    # Then: it raises instead of silently broadening to an unfiltered search,
    # and the engine stays usable afterwards.
    with pytest.raises(LabelError):
        dex.search("alpha", labels="project:fine")
    assert [h["slug"] for h in dex.search("alpha")] == ["note"]


def test_invalid_label_filter_raises_before_any_refresh(tmp_path, monkeypatch):
    # Given: a fresh engine whose refresh would scan the vault, and a note
    # that scan would index.
    _write(tmp_path, "note", "alpha body", labels=("project:fine",))
    refreshed: list[bool] = []
    monkeypatch.setattr(mnemosyne.Mnemosyne, "refresh",
                        lambda self: refreshed.append(True))
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: the malformed request is refused on a never-loaded engine.
    # Then: it raises before refresh, so the rejected request has no
    # index/cache lookup side effects; a valid request still refreshes.
    with pytest.raises(LabelError):
        dex.search("alpha", labels=["bad"])
    assert refreshed == []
    dex.search("alpha")
    assert refreshed == [True]


def test_malformed_on_disk_labels_keep_recall_and_never_match(tmp_path):
    # Given: a well-formed note and one whose labels metadata is malformed in
    # each of two ways (a non-list scalar, and a list with an invalid entry).
    _write(tmp_path, "good", "alpha body", labels=("project:ok",))
    (tmp_path / "scalar.md").write_text(
        "---\ntitle: scalar\nlabels: BAD_SCALAR\n---\n\nalpha body\n",
        encoding="utf-8")
    (tmp_path / "entry.md").write_text(
        '---\ntitle: entry\nlabels: ["NO_COLON_ENTRY"]\n---\n\nalpha body\n',
        encoding="utf-8")
    dex = mnemosyne.Mnemosyne(tmp_path)

    # When: the same query is searched unfiltered and with a label filter.
    # Then: malformed metadata never breaks unfiltered recall and never
    # counts as a matching label — for the valid label and for others.
    assert {h["slug"] for h in dex.search("alpha")} == {
        "good", "scalar", "entry"}
    assert [h["slug"] for h in dex.search("alpha", labels=["project:ok"])] == ["good"]
    assert dex.search("alpha", labels=["lang:en"]) == []
    scalar_meta = dex.note_meta("scalar")
    entry_meta = dex.note_meta("entry")
    assert scalar_meta is not None and entry_meta is not None
    assert scalar_meta["labels"] == []
    assert entry_meta["labels"] == []
