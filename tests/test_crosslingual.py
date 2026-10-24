"""Cross-language candidate6 reranking: wire contract, merge, pairwise order, client."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from birkin_mnemosyne import RerankError, opengateway_decider, translate_views
from birkin_mnemosyne.crosslingual import (
    EXCERPT_CHARS,
    MAX_CARDS,
    MODEL,
    Card,
    aggregate_preferences,
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
