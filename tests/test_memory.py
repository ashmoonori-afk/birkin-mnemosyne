import config
import pytest
from birkin_mnemosyne import VaultMemory


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
