"""Cross-language candidate6 reranking: wire contract, merge, pairwise order, client."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from birkin_mnemosyne import RerankError, opengateway_decider, translate_views
from birkin_mnemosyne.crosslingual import (
    CONCURRENCY,
    EXCERPT_CHARS,
    MAX_CARDS,
    MODEL,
    Card,
    _map,
    aggregate_preferences,
    configured,
    expanded_union,
    merge_top,
    pair_packet,
    pairwise_order,
    passage,
    pointwise_packet,
    score_cards,
)
from birkin_mnemosyne.kibitzer import KibitzerAdapter


class Judge:
    """Deterministic stand-in for the hosted judge.

    Pointwise packets get ``relevance[path]``; a pair packet asks whether c0 beats
    c1 and gets ``strength[c0] / (strength[c0] + strength[c1])``.
    """

    def __init__(self, relevance: dict[str, float], strength: dict[str, float],
                 c0_bias: float = 0.0) -> None:
        self.relevance, self.strength, self.c0_bias = relevance, strength, c0_bias
        self.packets: list[dict[str, Any]] = []

    def __call__(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.packets.append(packet)
        cards = packet["state"]["cards"]
        if len(packet["questions"]) == 1 and len(cards) == 2:
            first, second = cards["c0"]["identity"], cards["c1"]["identity"]
            p = self.strength[first] / (self.strength[first] + self.strength[second])
            return {"model": MODEL, "answers": {"c0": {"type": "noul",
                                                       "noul": min(1.0, p + self.c0_bias)}}}
        return {"model": MODEL, "answers": {
            key: {"type": "noul", "noul": self.relevance.get(card["identity"], 0.0)}
            for key, card in cards.items()}}


def card(name: str, snippet: str = "evidence") -> Card:
    return Card(name, name.upper(), snippet)


def test_pointwise_packet_scores_each_card_alone_without_truncating() -> None:
    title = "x" * 199 + "\U0001f680tail"
    snippet = "\U0001f680" * EXCERPT_CHARS
    packet = pointwise_packet("query", [Card("a.md", title, snippet), card("b.md")])
    assert set(packet) == {"model", "state", "questions"}
    assert packet["model"] == MODEL
    assert list(packet["state"]["cards"]) == list(packet["questions"]) == ["c0", "c1"]
    first = packet["state"]["cards"]["c0"]
    assert first["identity"] == "a.md" and first["body"] == snippet
    assert len(first["description"].encode("utf-16-le")) // 2 <= 200
    for key, question in packet["questions"].items():
        assert question["type"] == "noul"
        assert question["instructions"].startswith(f"Use state.cards.{key} only. ")
        assert set(question["criteria"]) == {"true", "false"}
    with pytest.raises(RerankError):
        pointwise_packet("query", [Card("a.md", "", "e" * (EXCERPT_CHARS + 1))])
    with pytest.raises(RerankError):
        pointwise_packet("query", [card(f"{i}.md") for i in range(MAX_CARDS + 1)])
    with pytest.raises(RerankError):
        pointwise_packet("query", [card("a.md"), card("a.md")])


def test_pair_packet_asks_one_scalar_question_about_two_cards() -> None:
    forward = pair_packet("query", card("a.md"), card("b.md"))
    reverse = pair_packet("query", card("b.md"), card("a.md"))
    assert list(forward["questions"]) == ["c0"]
    assert forward["questions"]["c0"]["type"] == "noul"
    assert [forward["state"]["cards"][k]["identity"] for k in ("c0", "c1")] == ["a.md", "b.md"]
    assert reverse["state"]["cards"]["c0"] == forward["state"]["cards"]["c1"]
    assert reverse["questions"] == forward["questions"]
    with pytest.raises(RerankError):
        pair_packet("query", card("a.md"), card("a.md"))


def test_expanded_union_keeps_the_original_prefix_and_never_recaps() -> None:
    original = [f"o{i}" for i in range(40)]
    english = ["o0", *[f"e{i}" for i in range(39)]]
    korean = [f"k{i}" for i in range(40)]
    union = expanded_union([original, english, korean], width=32)
    assert union[:32] == original[:32]
    assert union[32:63] == english[1:32]
    assert union[63:] == korean[:32]
    assert len(union) == len(set(union)) == 95
    assert "o35" not in union


def test_passage_picks_the_window_with_the_rarest_query_terms() -> None:
    body = "common " * 400 + "autoscaler adds nodes " + "common " * 400
    excerpt = passage("When does the autoscaler add nodes", body,
                      {"autoscaler": 1, "nodes": 3, "common": 900}, 1000)
    assert len(excerpt) == EXCERPT_CHARS and "autoscaler" in excerpt
    assert passage("query", "short", {}, 0) == "short"


def test_merge_averages_shared_notes_and_breaks_ties_by_retriever_position() -> None:
    bm25 = [card("a.md"), card("b.md"), card("c.md")]
    cosine = [card("c.md"), card("d.md")]
    top = merge_top(bm25, [0.5, 0.5, 0.2], cosine, [1.0, 0.5], keep=4)
    assert [c.path for c in top] == ["c.md", "a.md", "b.md", "d.md"]
    with pytest.raises(RerankError):
        merge_top(bm25, [0.5, 0.5, 0.2], [card("c.md", "other text")], [1.0])


def test_pairwise_order_is_symmetric_and_preserves_membership() -> None:
    five = [card(name) for name in ("a.md", "b.md", "c.md", "d.md", "e.md")]
    strength = {"a.md": 1.0, "b.md": 2.0, "c.md": 9.0, "d.md": 3.0, "e.md": 4.0}
    judge = Judge({}, strength)
    ordered = pairwise_order(judge, "query", five)
    assert [c.path for c, _ in ordered] == ["c.md", "e.md", "d.md", "b.md", "a.md"]
    assert len(judge.packets) == 5 * 4
    assert sum(total for _, total in ordered) == pytest.approx(10)

    biased = Judge({}, {name: 1.0 for name in strength}, c0_bias=0.25)
    assert [c.path for c, _ in pairwise_order(biased, "query", five)] == \
        [c.path for c in five]


def test_preference_aggregation_rejects_incomplete_coverage() -> None:
    assert aggregate_preferences(2, {(0, 1): 0.25}) == [(1, 0.75), (0, 0.25)]
    with pytest.raises(RerankError):
        aggregate_preferences(3, {(0, 1): 0.5, (0, 2): 0.5})


@pytest.mark.parametrize("response", [
    {"model": MODEL, "answers": {"c0": {"type": "noul", "noul": 0.5}}},
    {"model": MODEL, "answers": {"c0": {"type": "noul", "noul": 1.5},
                                 "c1": {"type": "noul", "noul": 0.5}}},
    {"model": MODEL, "answers": {"c0": {"type": "noul", "noul": True},
                                 "c1": {"type": "noul", "noul": 0.5}}},
    {"model": "other/model", "answers": {"c0": {"type": "noul", "noul": 0.5},
                                         "c1": {"type": "noul", "noul": 0.5}}},
], ids=["missing-card", "out-of-range", "boolean", "other-model"])
def test_invalid_judge_answers_raise_instead_of_ranking(response: dict[str, Any]) -> None:
    with pytest.raises(RerankError):
        score_cards(lambda packet: response, "query", [card("a.md"), card("b.md")])


def _vault(root: Path) -> Path:
    notes = {
        "autoscale.md": ("cluster autoscaler node scaling",
                         "The cluster autoscaler adds nodes when pods cannot be scheduled."),
        "rollout.md": ("rolling update deployment",
                       "A rolling update replaces pods one at a time in the cluster."),
        "garbage.md": ("garbage collection owners",
                       "Garbage collection removes cluster objects without an owner."),
        "ingress.md": ("ingress controller dns",
                       "The ingress controller routes cluster traffic by host name."),
        "quota.md": ("resource quota namespace",
                     "A resource quota limits cluster usage per namespace."),
        "private.md": ("cluster autoscaler secrets", "Already surfaced cluster autoscaler note."),
        "korean.md": ("노드 자동 확장", "클러스터 오토스케일러는 파드를 배치할 수 없을 때 노드를 추가합니다."),
    }
    for name, (description, body) in notes.items():
        (root / name).write_text(f"---\ndescription: {description}\n---\n{body}\n", "utf-8")
    return root


def test_select_crosslingual_runs_all_stages_and_honours_exclusions(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    adapter = KibitzerAdapter(vault)
    query = "클러스터 오토스케일러 노드 추가"
    english = "When does the cluster autoscaler add nodes"
    relevance = {"autoscale.md": 0.9, "korean.md": 0.95, "rollout.md": 0.4,
                 "garbage.md": 0.3, "ingress.md": 0.35, "quota.md": 0.2}
    strength = {"autoscale.md": 8.0, "korean.md": 2.0, "rollout.md": 1.5,
                "garbage.md": 1.0, "ingress.md": 1.2, "quota.md": 0.5}

    # Given only the Korean query, the English-only notes never become candidates.
    native = Judge(relevance, strength)
    alone = adapter.select_crosslingual(query, decide=native, surfaced={"private.md"})
    assert [c.path for c in alone] == ["korean.md"]

    # When the English view is added, the union reaches English notes, and the
    # pairwise stage overrides the pointwise winner.
    judge = Judge(relevance, strength)
    ranked = adapter.select_crosslingual(query, decide=judge, views=[english],
                                         surfaced={"private.md"})
    assert ranked[0].path == "autoscale.md"
    assert "korean.md" in [c.path for c in ranked]
    assert [c.score for c in ranked] == sorted(c.score for c in ranked)
    assert len(ranked) == 5

    pointwise = [p for p in judge.packets if len(p["questions"]) == len(p["state"]["cards"])]
    pairs = [p for p in judge.packets if p not in pointwise]
    assert len(pairs) == 5 * 4
    sent = {c["identity"] for p in judge.packets for c in p["state"]["cards"].values()}
    assert "private.md" not in sent
    assert all(p["state"]["original_query"] == query for p in judge.packets)
    assert all(len(p["state"]["cards"]) <= MAX_CARDS for p in pointwise)

    assert adapter.select_crosslingual(query, decide=judge, views=[english], limit=2,
                                       surfaced={"private.md"})[0].path == "autoscale.md"
    with pytest.raises(ValueError):
        adapter.select_crosslingual(query, decide=judge, limit=6)
    assert adapter.select_crosslingual("zzzz qqqq", decide=judge) == ()


def test_translate_views_skips_the_source_language_and_duplicates() -> None:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return "  same\nview "

    assert translate_views("질문", "ko", complete) == ("same view",)
    assert len(prompts) == 1 and "English" in prompts[0]
    assert translate_views("q", "fr", complete) == ("same view",)
    with pytest.raises(RerankError):
        translate_views("q", "fr", lambda prompt: "  ")


class _Handler(BaseHTTPRequestHandler):
    received: list[tuple[dict[str, str], bytes]] = []
    status = 200
    location = ""

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        body = self.rfile.read(int(self.headers["content-length"]))
        type(self).received.append((dict(self.headers), body))
        self.send_response(type(self).status)
        if type(self).location:
            self.send_header("location", type(self).location)
        payload = json.dumps({"model": MODEL, "answers": {
            "c0": {"type": "noul", "noul": 0.25}}}).encode()
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        return


@pytest.fixture
def server():
    _Handler.received, _Handler.status, _Handler.location = [], 200, ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1/decisions"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_opengateway_decider_posts_json_with_bearer_key(server: str) -> None:
    decide = opengateway_decider("test-key-123", endpoint=server)
    packet = pair_packet("질문", card("a.md"), card("b.md"))
    assert score_cards(lambda p: decide(p), "q", [card("a.md")]) == [0.25]
    assert decide(packet)["answers"]["c0"]["noul"] == 0.25
    headers, body = _Handler.received[-1]
    lowered = {k.lower(): v for k, v in headers.items()}
    assert lowered["authorization"] == "Bearer test-key-123"
    assert lowered["content-type"] == "application/json"
    assert json.loads(body) == packet
    assert "질문".encode() in body


@pytest.mark.parametrize("status,location", [(500, ""), (307, "http://127.0.0.1:9/x")],
                         ids=["server-error", "redirect-refused"])
def test_opengateway_decider_raises_on_non_200(server: str, status: int, location: str) -> None:
    _Handler.status, _Handler.location = status, location
    decide = opengateway_decider("test-key-123", endpoint=server)
    with pytest.raises(RerankError):
        decide(pair_packet("q", card("a.md"), card("b.md")))
    assert len(_Handler.received) == 1


def test_opengateway_decider_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENGATEWAY_API_KEY", raising=False)
    with pytest.raises(RerankError):
        opengateway_decider()


_RERANK_ENV = ("MNEMOSYNE_RERANK", "MNEMOSYNE_RERANK_API_KEY", "MNEMOSYNE_RERANK_TIMEOUT",
               "MNEMOSYNE_RERANK_TRANSLATOR")
_QUERY = "When does the cluster autoscaler add nodes"
_RELEVANCE = {"autoscale.md": 0.9, "korean.md": 0.95, "rollout.md": 0.4,
              "garbage.md": 0.3, "ingress.md": 0.35, "quota.md": 0.2, "private.md": 0.1}
_STRENGTH = {"autoscale.md": 8.0, "korean.md": 2.0, "rollout.md": 1.5,
             "garbage.md": 1.0, "ingress.md": 1.2, "quota.md": 0.5, "private.md": 0.2}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (*_RERANK_ENV, "OPENGATEWAY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and r.name == "birkin_mnemosyne.kibitzer"]


def test_recall_reranks_automatically_with_a_configured_client(
        tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    judge = Judge(_RELEVANCE, _STRENGTH)
    adapter = KibitzerAdapter(_vault(tmp_path), decide=judge)
    result = adapter.recall(_QUERY, limit=5)
    assert (result.selector, result.fallback) == ("crosslingual-rerank", None)
    strict = adapter.select_crosslingual(_QUERY, decide=Judge(_RELEVANCE, _STRENGTH))
    assert result.candidates == strict
    assert result.candidates[0].path == "autoscale.md"
    assert len([p for p in judge.packets if len(p["questions"]) == 1
                and len(p["state"]["cards"]) == 2]) == 20


def test_recall_without_a_key_sends_nothing_and_warns_once(
        tmp_path: Path, clean_env: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    # A key exported for another tool must not enable the rerank.
    clean_env.setenv("OPENGATEWAY_API_KEY", "other-tool-key")
    adapter = KibitzerAdapter(_vault(tmp_path))
    with caplog.at_level(logging.WARNING):
        first = adapter.recall(_QUERY)
        second = adapter.recall(_QUERY)
    assert first == second
    assert (first.selector, first.fallback) == ("mnemosyne-bm25", "no-key")
    assert first.candidates == adapter.select(_QUERY)
    assert len(_warnings(caplog)) == 1 and "MNEMOSYNE_RERANK_API_KEY" in _warnings(caplog)[0]


@pytest.mark.parametrize("failure", [RerankError("bad answer"), TimeoutError("timed out"),
                                     OSError("connection reset")],
                         ids=["contract", "timeout", "network"])
def test_recall_falls_back_cleanly_on_any_judge_failure(
        tmp_path: Path, clean_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
        failure: Exception) -> None:
    calls: list[dict[str, Any]] = []

    def broken(packet: dict[str, Any]) -> dict[str, Any]:
        calls.append(packet)
        raise failure

    adapter = KibitzerAdapter(_vault(tmp_path), decide=broken)
    with caplog.at_level(logging.WARNING):
        result = adapter.recall(_QUERY, limit=5)
    assert (result.selector, result.fallback) == ("mnemosyne-bm25", "error")
    assert result.candidates == adapter.select(_QUERY, limit=5)
    assert len(_warnings(caplog)) == 1 and type(failure).__name__ in _warnings(caplog)[0]
    # The first failure cancels queued requests: at most one batch was attempted.
    assert 1 <= len(calls) <= CONCURRENCY


def test_recall_falls_back_when_translation_fails(
        tmp_path: Path, clean_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    judge = Judge(_RELEVANCE, _STRENGTH)
    adapter = KibitzerAdapter(_vault(tmp_path), decide=judge, complete=lambda prompt: " ")
    with caplog.at_level(logging.WARNING):
        result = adapter.recall(_QUERY)
    assert result.fallback == "error" and judge.packets == []
    assert len(_warnings(caplog)) == 1


def test_off_switch_and_limits_never_call_the_judge(
        tmp_path: Path, clean_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    judge = Judge(_RELEVANCE, _STRENGTH)
    adapter = KibitzerAdapter(_vault(tmp_path), decide=judge)
    with caplog.at_level(logging.WARNING):
        assert adapter.recall(_QUERY, rerank=False).fallback == "disabled"
        assert adapter.recall(_QUERY, limit=6).fallback == "limit"
        assert adapter.recall(_QUERY, limit=0).candidates == ()
        for value in ("off", "0", "FALSE", " no "):
            clean_env.setenv("MNEMOSYNE_RERANK", value)
            clean_env.setenv("MNEMOSYNE_RERANK_API_KEY", "configured-key")
            off = adapter.recall(_QUERY)
            assert (off.selector, off.fallback) == ("mnemosyne-bm25", "off")
            assert off.candidates == adapter.select(_QUERY)
    assert judge.packets == []
    assert _warnings(caplog) == []


def test_configured_reads_only_mnemosyne_settings(clean_env: pytest.MonkeyPatch) -> None:
    assert configured({}).status == "no-key"
    assert configured({"OPENGATEWAY_API_KEY": "k"}).status == "no-key"
    assert configured({"MNEMOSYNE_RERANK": "off", "MNEMOSYNE_RERANK_API_KEY": "k"}).status == "off"
    enabled = configured({"MNEMOSYNE_RERANK_API_KEY": "k", "MNEMOSYNE_RERANK": "on"})
    assert enabled.status == "configured" and callable(enabled.decide)
    assert enabled.complete is None
    for timeout in ("soon", "0", "-1", "nan"):
        with pytest.raises(RerankError):
            configured({"MNEMOSYNE_RERANK_API_KEY": "k", "MNEMOSYNE_RERANK_TIMEOUT": timeout})


def test_misconfigured_environment_falls_back_with_one_warning(
        tmp_path: Path, clean_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    clean_env.setenv("MNEMOSYNE_RERANK_API_KEY", "k")
    clean_env.setenv("MNEMOSYNE_RERANK_TIMEOUT", "soon")
    adapter = KibitzerAdapter(_vault(tmp_path))
    with caplog.at_level(logging.WARNING):
        result = adapter.recall(_QUERY)
    assert result.fallback == "error" and result.candidates == adapter.select(_QUERY)
    assert len(_warnings(caplog)) == 1


def test_parallel_judge_calls_are_bounded_and_keep_order() -> None:
    barrier = threading.Barrier(CONCURRENCY, timeout=10)
    lock, active, peak = threading.Lock(), [0], [0]

    def call(item: int) -> int:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        barrier.wait()  # proves CONCURRENCY calls were in flight together
        with lock:
            active[0] -= 1
        return item * item

    assert _map(call, list(range(2 * CONCURRENCY)), CONCURRENCY) == \
        [i * i for i in range(2 * CONCURRENCY)]
    assert peak[0] == CONCURRENCY
    assert _map(lambda x: x + 1, [1, 2, 3], 1) == [2, 3, 4]
