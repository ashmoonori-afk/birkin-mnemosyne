import config
import pytest
from birkin_mnemosyne import VaultMemory, frontmatter


def _mem():
    return VaultMemory(config.load_config())


def test_write_and_get_note_roundtrip():
    m = _mem()
    m.write_note("FlowerPlus GTM", "Corporate welfare flowers.", note_type="project")
    text = m.get_note("FlowerPlus GTM")
    assert text is not None
    assert "Corporate welfare flowers." in text
    assert "type: project" in text


def test_search_finds_by_keyword():
    m = _mem()
    m.write_note("Topic A", "alpha beta gamma", note_type="topic")
    m.write_note("Topic B", "delta epsilon", note_type="topic")
    hits = m.search("gamma")
    assert any("topic-a" == h["title"] for h in hits)


def test_wikilink_neighbors():
    m = _mem()
    m.write_note("Project X", "Relates to things.", links=["Research Y"])
    assert "Research Y" in m.neighbors("Project X")


def test_add_link():
    m = _mem()
    m.write_note("A", "body a")
    m.write_note("B", "body b")
    assert m.add_link("A", "B") is True
    assert "B" in m.neighbors("A")


def _meta(m, title):
    return frontmatter.parse(m.get_note(title))[0]


def test_add_link_keeps_tags_and_expiry():
    m = _mem()
    m.write_note("A", "body a", tags=["a", "b"], ttl_days=30)
    m.write_note("B", "body b")
    before = _meta(m, "A")
    assert before["tags"] == ["a", "b"] and before["expires_at"]
    assert m.add_link("A", "B") is True
    after = _meta(m, "A")
    assert after["tags"] == ["a", "b"]
    assert after["expires_at"] == before["expires_at"]


def test_append_without_tags_or_ttl_keeps_both():
    m = _mem()
    m.write_note("A", "first", tags=["a", "b"], ttl_days=30)
    before = _meta(m, "A")
    m.write_note("A", "second", append=True)
    after = _meta(m, "A")
    assert after["tags"] == ["a", "b"]
    assert after["expires_at"] == before["expires_at"]


def test_explicit_empty_tags_clear_and_new_ttl_replaces_expiry():
    m = _mem()
    m.write_note("A", "first", tags=["a", "b"], ttl_days=30)
    old = _meta(m, "A")["expires_at"]
    m.write_note("A", "second", tags=[], ttl_days=90)
    after = _meta(m, "A")
    assert after["tags"] == []
    assert after["expires_at"] and after["expires_at"] != old


def test_add_link_tolerates_non_numeric_stored_confidence():
    m = _mem()
    m.write_note("A", "body a", confidence="high")
    m.write_note("B", "body b")
    assert m.add_link("A", "B") is True
    assert "B" in m.neighbors("A")


def test_render_digest_lists_notes():
    m = _mem()
    m.write_note("Note One", "first", note_type="fact")
    digest = m.render()
    assert "[[Note One]]" in digest


def test_list_notes_counts():
    m = _mem()
    m.write_note("N1", "x")
    m.write_note("N2", "y")
    titles = {n["title"] for n in m.list_notes()}
    assert {"N1", "N2"} <= titles


def test_get_missing_note_returns_none():
    assert _mem().get_note("does-not-exist") is None


def test_near_duplicates_flags_twin(tmp_path):
    m = _mem()
    body = "the rsync deploy to staging failed twice before the fix " * 3
    m.write_note("deploy failure", body)
    dups = m.near_duplicates("deploy failure copy", body)
    assert dups and dups[0][0] == "deploy-failure"
    assert dups[0][1] >= 0.6


def test_near_duplicates_excludes_self_and_unrelated():
    m = _mem()
    m.write_note("deploy failure", "rsync staging deploy failed twice fix " * 3)
    # re-writing the same note never flags itself
    same = m.near_duplicates("deploy failure",
                             "rsync staging deploy failed twice fix " * 3)
    assert all(slug != "deploy-failure" for slug, _ in same)
    # an unrelated note is below the link threshold
    un = m.near_duplicates("tomato care",
                           "garden tomato seedlings sunlight water weekly " * 3)
    assert all(sim < 0.35 for _, sim in un)


def test_korean_query_snippet_finds_bigram_match():
    m = _mem()
    m.write_note("배포 실패", "어제 저녁 스테이징 서버 배포가 두 번 실패했다 " * 3)
    hits = m.search("배포 실패")
    assert hits
    # snippet uses the bigram tokenizer, so it locates the matched passage
    assert "배포" in hits[0]["snippet"]


def test_vault_dir_honors_legacy_vault_key(tmp_path):
    from birkin_mnemosyne.memory import _vault_dir
    d = _vault_dir({"vault": str(tmp_path / "legacy")})
    assert d.name == "legacy" and d.exists()          # not ./vault


def test_snippet_boundary_term_survives():
    from birkin_mnemosyne.memory import _snippet
    text = "alpha" + ("x" * 233) + "beta"
    s = _snippet(text, ["alpha", "beta"], width=240)
    assert "alpha" in s and "beta" in s


def test_snippet_matches_accented_text_with_folded_terms():
    from birkin_mnemosyne.memory import _snippet
    text = ("x " * 200) + "La paella lleva azafrán y garrofón." + (" y" * 200)
    assert "azafrán" in _snippet(text, ["azafran"], width=60)


@pytest.mark.parametrize("passage, query", [
    ("die Straße ist gesperrt", "strasse"),
    ("ＡＰＩ key rotated", "api"),
    ("ｶﾞｲﾄﾞ lesson booked", "ガイド"),
])
def test_snippet_finds_late_passage_under_tokenizer_normalization(passage, query):
    from birkin_mnemosyne.memory import _snippet
    from birkin_mnemosyne.mnemosyne import tokenize
    text = ("filler words here " * 30) + passage + (" tail" * 10)
    assert passage in _snippet(text, tokenize(query), width=80)


def test_snippet_finds_passage_matched_only_through_a_stem():
    from birkin_mnemosyne.memory import _snippet
    from birkin_mnemosyne.mnemosyne import tokenize
    passage = "Der Vertrag verlängert sich automatisch"
    text = ("filler words here " * 30) + passage + (" tail" * 10)
    assert "verlängert" in _snippet(text, tokenize("Verlängerung"), width=80)


def test_snippet_finds_decomposed_hangul():
    import unicodedata
    from birkin_mnemosyne.memory import _snippet
    from birkin_mnemosyne.mnemosyne import tokenize
    passage = unicodedata.normalize("NFD", "배추 가격이 올랐다")
    text = ("filler words here " * 30) + passage + (" tail" * 10)
    assert passage in _snippet(text, tokenize("가격"), width=80)


def test_stem_snippet_ignores_words_the_tokenizer_would_not_stem():
    from birkin_mnemosyne.memory import _snippet
    from birkin_mnemosyne.mnemosyne import tokenize
    early = "note verla 123 and verla99 here"
    passage = "Der Vertrag verlängert sich automatisch"
    text = early + (" filler words here" * 30) + " " + passage + (" tail" * 10)
    assert "verlängert" in _snippet(text, tokenize("Verlängerung"), width=80)


def test_stem_snippet_word_ends_at_cjk_like_the_tokenizer():
    from birkin_mnemosyne.memory import _stem_word_at
    assert not _stem_word_at("abcde漢字", 0)
    assert _stem_word_at("abcdef漢字", 0)


def _vault_mem(tmp_path):
    return VaultMemory({"vault_path": str(tmp_path / "v")})


def _md_names(vault):
    return sorted(p.name for p in vault.rglob("*.md"))


def test_hand_made_note_title_round_trips_through_get_and_write(tmp_path):
    m = _vault_mem(tmp_path)
    hand = m.vault / "My Note.md"
    hand.write_text("---\ntype: topic\n---\nhand written body about pelicans\n",
                    encoding="utf-8")
    m.dex.refresh()
    hits = m.search("pelicans")
    assert hits and hits[0]["title"] == "My Note"
    text = m.get_note(hits[0]["title"])
    assert text is not None and "pelicans" in text
    assert m.write_note("My Note", "more about herons", append=True) == hand
    updated = hand.read_text(encoding="utf-8")
    assert "pelicans" in updated and "herons" in updated
    assert _md_names(m.vault) == ["My Note.md"]


def test_nfd_title_names_the_same_note_as_nfc(tmp_path):
    import unicodedata
    nfc = "\ud55c\uae00 note"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    m = _vault_mem(tmp_path)
    first = m.write_note(nfc, "first body")
    assert m.write_note(nfd, "second body", append=True) == first
    assert len(_md_names(m.vault)) == 1
    text = m.get_note(nfd)
    assert text is not None and "first body" in text and "second body" in text


def test_existing_nfd_named_file_stays_reachable_by_nfc_title(tmp_path):
    import unicodedata
    nfc = "\ud55c\uae00 note"
    hand = (tmp_path / "v") / (unicodedata.normalize("NFD", nfc) + ".md")
    hand.parent.mkdir()
    hand.write_text("---\ntype: topic\n---\ndecomposed file name body\n",
                    encoding="utf-8")
    m = VaultMemory({"vault_path": str(hand.parent)})
    text = m.get_note(nfc)
    assert text is not None and "decomposed file name body" in text
    assert m.write_note(nfc, "added later", append=True) == hand
    assert len(_md_names(m.vault)) == 1


_EXPIRED = "---\ntype: topic\nexpires_at: 2000-01-01\n---\nstale body\n"


def _plant_hidden_and_nested(vault):
    planted = []
    for rel in (".trash/foo.md", ".obsidian/x.md", "a/b/deep.md"):
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_EXPIRED, encoding="utf-8")
        planted.append(p)
    return planted


def test_get_note_fallback_skips_hidden_and_nested_folders(tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    _plant_hidden_and_nested(vault)
    m = VaultMemory({"vault_path": str(vault)})
    assert m.get_note("foo") is None
    assert m.get_note("x") is None
    assert m.get_note("deep") is None


def test_purge_expired_leaves_hidden_and_nested_folders_alone(tmp_path):
    vault = tmp_path / "v"
    (vault / "knowledge").mkdir(parents=True)
    planted = _plant_hidden_and_nested(vault)
    zoned = vault / "knowledge" / "old.md"
    zoned.write_text(_EXPIRED, encoding="utf-8")
    m = VaultMemory({"vault_path": str(vault)})
    assert m.purge_expired() == 1
    assert not zoned.exists()
    assert all(p.exists() for p in planted)


# -- frontmatter quoting (M1-9 / M1-11) ----------------------------------------

_AWKWARD_TITLES = [
    "Nan", "Infinity", "Inf", "1e3", "007", "true", "null", "[a, b]",
    'He said "hi" \\ bye',
]


@pytest.mark.parametrize("title", _AWKWARD_TITLES)
def test_awkward_titles_roundtrip_unchanged(title):
    from birkin_mnemosyne import frontmatter
    m = _mem()
    m.write_note(title, "body text", source="seed")
    meta, _ = frontmatter.parse(m.get_note(title))
    assert meta["title"] == title
    assert [n["title"] for n in m.list_notes()] == [title]
    m.write_note(title, "second", source="seed2")
    meta, _ = frontmatter.parse(m.get_note(title))
    assert meta["version"] == 2
    assert meta["sources"] == ["seed", "seed2"]


def test_numeric_title_survives_add_link():
    m = _mem()
    m.write_note("007", "agent", source="s")
    m.write_note("B", "other", source="s")
    assert m.add_link("007", "B") is True
    assert "B" in m.neighbors("007")


def test_source_with_quote_and_tag_with_comma_roundtrip():
    from birkin_mnemosyne import frontmatter
    m = _mem()
    src = 'https://x.test/?q="a"&b=\\c'
    tags = ["a,b", "c]d", 'e"f', "plain"]
    m.write_note("Quoted", "body", source=src, tags=tags)
    meta, _ = frontmatter.parse(m.get_note("Quoted"))
    assert meta["sources"] == [src]
    assert meta["tags"] == tags
    m.write_note("Quoted", "again", tags=tags)
    meta, _ = frontmatter.parse(m.get_note("Quoted"))
    assert meta["version"] == 2
    assert meta["sources"] == [src]


def test_multiline_title_cannot_break_header():
    from birkin_mnemosyne import frontmatter
    m = _mem()
    m.write_note("Plan\n---\nnotes", "body", source="seed", tags=["t\n---"])
    m.write_note("Plan\n---\nnotes", "body2", source="seed")
    text = m.get_note("Plan --- notes")
    meta, body = frontmatter.parse(text)
    assert meta["version"] == 2
    assert meta["sources"] == ["seed"]
    assert meta["title"] == "Plan --- notes"
    assert "---" not in body.replace("body2", "")
    m.write_note("Plan --- notes", "body3", expected_version=2)


def test_old_unquoted_frontmatter_still_parses():
    from birkin_mnemosyne import frontmatter
    old = (
        "---\ntitle: Old Note\ntype: topic\ncreated: 2026-01-02\n"
        "updated: 2026-01-03\nconfidence: 0.7\npolarity: positive\n"
        'version: 3\nsources: ["https://a.test", "b"]\n'
        "tags: [x, y z]\nexpires_at: 2099-01-01\n---\n\nhello\n"
    )
    meta, body = frontmatter.parse(old)
    assert meta["title"] == "Old Note"
    assert meta["confidence"] == 0.7
    assert meta["version"] == 3
    assert meta["sources"] == ["https://a.test", "b"]
    assert meta["tags"] == ["x", "y z"]
    assert meta["created"] == "2026-01-02"
    assert body.strip() == "hello"


@pytest.mark.parametrize("raw,expected", [
    ("Nan", "Nan"), ("inf", "inf"), ("Infinity", "Infinity"),
    ("1e3", "1e3"), ("007", "007"), ("42", 42), ("-3", -3),
    ("0.7", 0.7), ("-1.5", -1.5), ("0", 0),
])
def test_parser_numeric_coercion_is_strict(raw, expected):
    from birkin_mnemosyne import frontmatter
    meta, _ = frontmatter.parse(f"---\nk: {raw}\n---\n")
    assert meta["k"] == expected
    assert type(meta["k"]) is type(expected)


def test_old_note_with_backslash_sources_survives_rewrite():
    from birkin_mnemosyne import frontmatter
    m = _mem()
    old_sources = ["D:\\notes\\todo", "C:\\Users\\x"]
    raw = (
        "---\ntitle: Old Paths\ntype: topic\ncreated: 2026-01-02\n"
        "updated: 2026-01-03\nconfidence: 0.7\npolarity: positive\n"
        'version: 1\nsources: ["D:\\notes\\todo", "C:\\Users\\x"]\n'
        "tags: []\n---\n\nbody\n"
    )
    (m.vault / "old-paths.md").write_text(raw, encoding="utf-8")
    meta, _ = frontmatter.parse(raw)
    assert meta["sources"] == old_sources
    m.reindex()
    m.write_note("Old Paths", "body two", source="extra")
    meta, _ = frontmatter.parse(m.get_note("Old Paths"))
    assert meta["sources"] == old_sources + ["extra"]
    assert meta["version"] == 2
    m.write_note("Old Paths", "body three")
    meta, _ = frontmatter.parse(m.get_note("Old Paths"))
    assert meta["sources"] == old_sources + ["extra"]


def test_source_with_literal_backslash_sequences_roundtrips():
    from birkin_mnemosyne import frontmatter
    m = _mem()
    srcs = ["a\\nb", 'q\\"r', "t\\\\u", "end\\", 'x"y\\', "\\u0041"]
    for i, src in enumerate(srcs):
        m.write_note(f"Esc {i}", "body", source=src, tags=[src])
        meta, _ = frontmatter.parse(m.get_note(f"Esc {i}"))
        assert meta["sources"] == [src]
        assert meta["tags"] == [src]
    m.write_note("Multi", "body", source=srcs[0], tags=srcs)
    meta, _ = frontmatter.parse(m.get_note("Multi"))
    assert meta["tags"] == srcs
