"""E8: Korean / mixed-language retrieval — BM25+bigram vs a real multilingual
embedding model (intfloat/multilingual-e5-large).

The synthetic Korean suite in bench.py (H2b) plants unique tokens, which is a
tokenizer stress test but says nothing about *semantic* Korean retrieval. Here
we use realistic Korean topic notes and three query styles, and put the
Hangul-bigram BM25 engine head to head with a strong multilingual encoder —
the setting most favorable to embeddings.

Query styles per target note:
  exact    a Korean phrase copied from the note
  partial  a shortened / reworded Korean cue (lexical overlap, not identical)
  mixed    a Korean–English code-switched query (e.g. "김치 fermentation 온도")

Reports Recall@5 and MRR@10 for each engine × style.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from birkin_mnemosyne.mnemosyne import bm25_scores, tokenize

# (topic, note_body, [(exact_q, partial_q, mixed_q), ...]) — hand-written so
# queries share *meaning* with the note, not just a planted unique token.
NOTES: list[tuple[str, str, tuple[str, str, str]]] = [
    ("김치", "배추를 소금에 절여 김치를 담근다. 고춧가루와 젓갈로 양념하고 발효 온도를 낮게 유지한다.",
     ("배추를 소금에 절여 김치", "김치 발효 온도", "김치 fermentation 온도")),
    ("된장찌개", "된장을 풀어 찌개를 끓인다. 두부와 애호박을 넣고 멸치 육수로 감칠맛을 낸다.",
     ("된장을 풀어 찌개", "된장찌개 육수", "된장찌개 broth 두부")),
    ("불고기", "간장과 배로 불고기를 재운다. 설탕과 참기름으로 양념하고 센 불에 빠르게 굽는다.",
     ("간장과 배로 불고기를 재운다", "불고기 양념", "불고기 marinade 간장")),
    ("비빔밥", "밥 위에 나물과 고추장을 올려 비빔밥을 만든다. 참기름을 두르고 계란을 얹는다.",
     ("나물과 고추장 비빔밥", "비빔밥 나물", "비빔밥 gochujang 나물")),
    ("수면", "잠들기 전 카페인을 피하고 방을 어둡게 한다. 규칙적인 취침 시간이 수면의 질을 높인다.",
     ("규칙적인 취침 시간 수면", "수면의 질", "수면 quality 카페인")),
    ("달리기", "아침에 30분씩 달리기를 한다. 무릎 부상을 막으려면 착지 자세와 신발이 중요하다.",
     ("아침에 30분씩 달리기", "달리기 무릎 부상", "달리기 knee 부상 신발")),
    ("전세계약", "전세 계약 전 등기부등본으로 근저당을 확인한다. 확정일자를 받아 보증금을 보호한다.",
     ("전세 계약 근저당 확인", "전세 보증금 보호", "전세 deposit 확정일자")),
    ("파이썬", "파이썬 리스트 컴프리헨션으로 반복문을 간결하게 쓴다. 제너레이터는 메모리를 아낀다.",
     ("파이썬 리스트 컴프리헨션", "파이썬 제너레이터 메모리", "파이썬 generator 메모리")),
    ("커피", "원두를 곱게 갈아 에스프레소를 내린다. 물 온도와 압력이 추출 맛을 좌우한다.",
     ("원두를 갈아 에스프레소", "에스프레소 추출 온도", "espresso 원두 추출")),
    ("등산", "북한산 능선을 오른다. 일교차가 크니 얇은 옷을 겹쳐 입고 물을 넉넉히 챙긴다.",
     ("북한산 능선 등산", "등산 일교차 준비물", "등산 hiking 준비물 물")),
    ("독서", "매일 밤 30쪽씩 소설을 읽는다. 읽은 문장을 노트에 옮겨 적으면 오래 기억에 남는다.",
     ("매일 밤 소설 읽기", "독서 노트 기억", "독서 note 기억")),
    ("환율", "달러 환율이 오르면 수입 물가가 오른다. 여행 전 환전 시점을 나눠 위험을 줄인다.",
     ("달러 환율 수입 물가", "환전 시점 분산", "환율 exchange 환전")),
    ("요가", "아침 요가로 굳은 몸을 풀어준다. 호흡에 맞춰 자세를 천천히 유지하는 것이 중요하다.",
     ("아침 요가 호흡 자세", "요가 호흡", "요가 yoga 호흡")),
    ("김장", "늦가을에 김장을 한다. 배추 스무 포기를 절이고 양념을 버무려 김치냉장고에 보관한다.",
     ("늦가을 배추 김장", "김장 배추 절이기", "김장 kimchi 보관")),
    ("주식", "장기 투자로 지수 추종 ETF를 매달 적립한다. 배당은 재투자해 복리 효과를 노린다.",
     ("지수 추종 ETF 적립", "주식 배당 재투자", "주식 ETF 배당 dividend")),
    ("사진", "황금시간대에 인물 사진을 찍는다. 조리개를 열어 배경을 흐리고 ISO를 낮춘다.",
     ("황금시간대 인물 사진", "사진 조리개 배경 흐림", "사진 aperture 배경")),
]


def rank_bm25(query: str, docs: dict[str, str]) -> list[str]:
    postings: dict[str, dict[str, int]] = {}
    doclens: dict[str, int] = {}
    for sid, text in docs.items():
        terms: dict[str, int] = {}
        for t in tokenize(text):
            terms[t] = terms.get(t, 0) + 1
        doclens[sid] = sum(terms.values())
        for t, tf in terms.items():
            postings.setdefault(t, {})[sid] = tf
    avgdl = (sum(doclens.values()) / len(doclens)) if doclens else 1.0
    scores = bm25_scores(tokenize(query), postings, doclens, avgdl, len(docs))
    return sorted(docs, key=lambda s: scores.get(s, 0.0), reverse=True)


def r5_mrr(ranks: list[int | None]) -> dict:
    n = len(ranks) or 1
    return {"recall@5": round(sum(r is not None and r <= 5 for r in ranks) / n, 3),
            "mrr@10": round(sum(1 / r for r in ranks if r) / n, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="intfloat/multilingual-e5-large")
    ap.add_argument("--out", default="benchmarks/results")
    args = ap.parse_args()

    ids = [f"n{i}" for i in range(len(NOTES))]
    docs = {i: body for i, (_t, body, _q) in zip(ids, NOTES)}

    from fastembed import TextEmbedding
    print(f"loading {args.model}…")
    emb = TextEmbedding(model_name=args.model)
    # e5 wants "passage:"/"query:" prefixes
    pref = "e5" in args.model.lower()
    doc_texts = [(f"passage: {docs[i]}" if pref else docs[i]) for i in ids]
    mat = np.array(list(emb.embed(doc_texts)), dtype=np.float32)
    mat /= (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)

    styles = ["exact", "partial", "mixed"]
    bm25_ranks = {s: [] for s in styles}
    embed_ranks = {s: [] for s in styles}
    for tgt, (i, (_t, _b, qs)) in enumerate(zip(ids, NOTES)):
        for si, style in enumerate(styles):
            q = qs[si]
            r = rank_bm25(q, docs)
            bm25_ranks[style].append(r.index(i) + 1 if i in r[:10] else None)
            qtext = f"query: {q}" if pref else q
            qv = np.array(list(emb.embed([qtext]))[0], dtype=np.float32)
            qv /= (np.linalg.norm(qv) + 1e-9)
            order = np.argsort(-(mat @ qv))
            ranked = [ids[j] for j in order]
            pos = ranked.index(i) + 1
            embed_ranks[style].append(pos if pos <= 10 else None)

    result = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "model": args.model, "n_notes": len(NOTES),
                       "n_queries_per_style": len(NOTES)},
              "bm25_bigram": {s: r5_mrr(bm25_ranks[s]) for s in styles},
              "multilingual_embed": {s: r5_mrr(embed_ranks[s]) for s in styles}}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"korean-embed-{datetime.now().strftime('%Y%m%d')}.json"
    p.write_text(json.dumps(result, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
