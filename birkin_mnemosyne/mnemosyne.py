"""Mnemosyne — the mechanical memory engine (zones, index, decay, priority).

Named after the Greek goddess of memory. This is the LLM-free half of
the Mnemosyne memory palace:

- **Index** — a stat-fingerprinted inverted index over the Obsidian vault, so
  ``search``/``render``/``list_notes`` never re-read the whole vault (closes
  the second half of review finding M4). Only changed files are re-parsed.
- **Zones** — notes live in one-level subdirectories of the vault
  (``vault/<zone>/note.md``, mempalace wing/room analog); the vault root is
  the *inbox*. ``_archive`` is the soft-forget zone (hermes curator's
  "archive, never delete").
- **BM25** — Okapi ranking over the index (k1/b as in mempalace's searcher),
  with a Unicode-aware tokenizer (NFKC + casefold, accent-folded Latin words,
  Hangul runs + bigrams, CJK unigrams + bigrams) and a small bonus for notes
  that match every script of a code-switched query. Limits: scripts whose
  words contain combining vowel signs (Devanagari, Thai) are split at those
  signs, because the stdlib ``re`` has no ``\\p{M}``; a TypeScript port
  should use ``[\\p{L}\\p{M}\\p{N}]`` with the ``u`` flag, iterate code points
  (astral Han), and emulate ``casefold`` (``ß`` -> ``ss``).
- **Dynamics** — per-note Ebbinghaus decay + Hebbian potentiation adapted
  from mempalace ``dynamics.py`` and — unlike mempalace — wired into ranking.
- **Zone priority** — per-zone EMA of accesses with daily decay; boosts
  retrieval and orders the prompt digest.

Judgment (which notes are truly related, where a note belongs, what to
archive) stays with Morpheus/the LLM; this module only produces mechanical
candidates and applies decisions.

Two sidecar files live next to the notes:

- ``.mnemosyne-index.json.z``  — CACHE (zlib JSON), rebuildable at any time.
- ``.mnemosyne-dynamics.json`` — STATE (usage); survives index rebuilds.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import unicodedata
import zlib
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import frontmatter
from .atomic import atomic_write, atomic_write_bytes

log = logging.getLogger(__name__)

# -- constants (single tuning source; see design §8) -------------------------

K1, B = 1.5, 0.75                     # Okapi BM25 (mempalace searcher.py)
CAND = 32                             # BM25 candidates before re-ranking
FUSE_DEPTH = 100                      # per-leg ranks fed to RRF (semantic)
RRF_K = 5                             # reciprocal-rank-fusion constant (dev-tuned)
SEM_WEIGHT = 0.4                      # semantic vote in the fusion (dev-tuned) ...
SEM_WEIGHT_CJK = 1.0                  # ... and for queries written mostly in Han/kana
STRENGTH_STEP, STRENGTH_CAP = 0.25, 5.0
STABILITY_INIT, STABILITY_GROWTH, STABILITY_CAP = 7.0, 1.5, 365.0
EFF_FLOOR = 0.05                      # nothing fully vanishes (mempalace)
SPACING_HOURS = 1.0                   # Cepeda spacing gate (mempalace)
ZONE_EMA_DECAY = 0.9                  # per-day zone priority decay
W_DYN, W_ZONE = 0.3, 0.2              # ranking boost weights
STALE_EFF, STALE_DAYS = 0.1, 90       # hermes curator archive tier
MAX_ZONES = 24
RELATED_LIMIT = 5                     # A-MEM: keep top-k small
RELATED_QUERY_TERMS = 12
INDEX_VERSION = 4                     # 2-3: Unicode tokenizer, stems; 4: zlib file
SCRIPT_BONUS = 0.5                    # per extra query script a note matches
STEM_PREFIX, STEM_MIN, STEM_MARK = 5, 6, "~"   # truncation stem of long words
SCAN_TTL = 2.0                        # search() stats the vault at most this often (s)
DIVERSITY_JACCARD = 0.9               # experimental lexical duplicate deferral
# Search-time query expansion: the weight of a term the caller adds to a query,
# graded by its distance from the query's own words (which weigh 1.0). Dev-tuned.
EXPANSION_WEIGHTS = {"synonyms": 0.75, "keywords": 0.75,
                     "related": 0.4, "note_line": 0.4}

_clock = time.monotonic               # module-level so tests can drive the TTL

INDEX_FILE = ".mnemosyne-index.json.z"
LEGACY_INDEX_FILE = ".mnemosyne-index.json"   # pre-v4 cache, removed on save
DYNAMICS_FILE = ".mnemosyne-dynamics.json"
ARCHIVE_ZONE = "_archive"
# identity is the always-rendered "L0" zone; it never counts as stale.
IDENTITY_ZONE = "identity"

ZONE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_CJK = ("\u3005\u3007\u3040-\u309f\u30a1-\u30fa\u30fc-\u30ff\u31f0-\u31ff"
        "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f")
_HANGUL = "\uac00-\ud7a3"
# one match per run: (CJK run | Hangul run | any other letters/digits)
_CJK_CHAR = re.compile(f"[{_CJK}]")
_RUN_RE = re.compile(rf"([{_CJK}]+)|([{_HANGUL}]+)|([^\W_{_CJK}{_HANGUL}]+)")

# Mechanical default placement for *new* notes (mempalace FOLDER_ROOM_MAP
# analog); Morpheus refines placement nightly via memory_rezone.
TYPE_ZONE = {
    "person": "people", "project": "projects", "preference": "identity",
    "fact": "knowledge", "topic": "knowledge", "session": "journal",
}


def slug(title: str) -> str:
    """Filesystem/wikilink slug (single source; memory.py re-exports)."""
    s = re.sub(r"[^\w\s-]", "", title.strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "note"


# -- pure functions -----------------------------------------------------------

def _fold_char(c: str) -> str:
    """Strip accents from Latin letters only (é -> e, ệ -> e); other scripts
    keep their marks (kana voicing marks, Cyrillic й)."""
    if ord(c) >= 0x250 and not "\u1e00" <= c <= "\u1eff":
        return c
    base = "".join(x for x in unicodedata.normalize("NFD", c)
                   if not unicodedata.combining(x))
    return base if len(base) == 1 else c


_HALFWIDTH_VOICING = frozenset("\uff9e\uff9f")


def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """``text`` normalised exactly like :func:`tokenize` sees it (NFKC,
    casefold, Latin accent folding) plus, for every normalised character,
    the index of the original character it came from (and ``len(text)`` as
    a final sentinel), so a match found in the normalised text can be cut
    out of the original. Works per base character + the marks that compose
    with it (combining marks, halfwidth voicing marks, Hangul medial/final
    jamo)."""
    if text.isascii():
        return text.lower(), list(range(len(text) + 1))
    out: list[str] = []
    offsets: list[int] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and (unicodedata.combining(text[j])
                         or text[j] in _HALFWIDTH_VOICING
                         or "\u1160" <= text[j] <= "\u11ff"):
            j += 1
        cluster = unicodedata.normalize("NFKC", text[i:j]).casefold()
        if not cluster.isascii():
            cluster = "".join(map(_fold_char, cluster))
        out.append(cluster)
        offsets.extend([i] * len(cluster))
        i = j
    offsets.append(n)
    return "".join(out), offsets


def tokenize(text: str) -> list[str]:
    """NFKC + casefold, then per run of one script class:

    - Latin/Cyrillic/... words -> one accent-folded token (``azafrán`` ->
      ``azafran``, ``Straße`` -> ``strasse``), plus for words of 6+ letters
      a truncation stem of their first 5 letters (``verlangerung`` ->
      ``verla~``) so inflections and compounds meet (``verlängert``);
    - Hangul runs -> the run + character bigrams (Korean without a
      morphological analyzer, unchanged from v1);
    - Han/kana runs -> character unigrams + bigrams (Chinese/Japanese have no
      spaces; unigrams keep one-character words, bigrams keep precision).
    """
    toks: list[str] = []
    norm = unicodedata.normalize("NFKC", text).casefold()
    for cjk, hangul, word in _RUN_RE.findall(norm):
        if word:
            folded = word if word.isascii() else "".join(map(_fold_char, word))
            toks.append(folded)
            if len(folded) >= STEM_MIN and folded.isalpha():
                toks.append(folded[:STEM_PREFIX] + STEM_MARK)
        elif hangul:
            toks.append(hangul)
            toks.extend(hangul[i:i + 2] for i in range(len(hangul) - 1))
        else:
            toks.extend(cjk)
            toks.extend(cjk[i:i + 2] for i in range(len(cjk) - 1))
    return toks


def _script(token: str) -> str:
    """Script class used by the code-switch bonus: "hangul", "cjk" (Han and
    kana together - one Japanese phrase mixes both), "latin" for every other
    letter, and "" for digit-only tokens, which belong to no language."""
    c = token[0]
    if "\uac00" <= c <= "\ud7a3":
        return "hangul"
    if _CJK_CHAR.match(c):
        return "cjk"
    return "" if token.isdigit() else "latin"


def expansion_weights(expansions: Mapping[str, Any],
                      literal: Iterable[str]) -> dict[str, float]:
    """{token: weight} for the terms a caller adds to a query at search time.

    ``expansions`` maps a tier of ``EXPANSION_WEIGHTS`` to a string or a list
    (or tuple) of strings; a one-shot iterator is refused, because callers
    read the value more than once. A token already among the query's own tokens (``literal``) is
    left out, so an expansion never counts a query word twice, and a token
    given in several tiers keeps its highest weight. Raises ``ValueError``
    for an unknown tier or a value that is not text."""
    lit = set(literal)
    out: dict[str, float] = {}
    for tier, value in expansions.items():
        weight = EXPANSION_WEIGHTS.get(tier)
        if weight is None:
            raise ValueError(f"unknown expansion tier {tier!r} "
                             f"(want one of {sorted(EXPANSION_WEIGHTS)})")
        if value is None:
            continue
        parts = [value] if isinstance(value, str) else value
        if (not isinstance(parts, (list, tuple))
                or not all(isinstance(p, str) for p in parts)):
            raise ValueError(f"expansion tier {tier!r} must be a string or a "
                             "list of strings")
        for t in tokenize(" ".join(parts)):
            if t not in lit and weight > out.get(t, 0.0):
                out[t] = weight
    return out


def bm25_scores(terms: list[str], postings: Mapping[str, Mapping[str, int | float]],
                doclens: dict[str, int], avgdl: float,
                n_docs: int, weights: Mapping[str, float] | None = None,
                script_bonus: bool = True) -> dict[str, float]:
    """Okapi BM25 over an inverted index; returns {slug: score}.

    Queries that mix scripts get a coordination factor ``1 + SCRIPT_BONUS x
    (scripts matched - 1)``: in a code-switched query ("moving checklist
    手続き") the rare English words otherwise let English notes that match
    only them outrank the note that matches both halves. Single-script
    queries are plain BM25.

    ``weights`` scales single terms (a term it does not name weighs 1.0) and
    ``script_bonus=False`` leaves the coordination factor out; both exist for
    expansion terms, which must stay weaker than the query's own words.
    """
    scores: dict[str, float] = {}
    scripts: dict[str, set[str]] = {}
    avgdl = avgdl or 1.0
    uniq = list(dict.fromkeys(terms))       # unique, order-preserving
    for t in uniq:
        post = postings.get(t)
        if not post:
            continue
        df = len(post)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        if weights is not None:
            idf *= weights.get(t, 1.0)
        script = _script(t)
        for s, tf in post.items():
            dl = doclens.get(s, avgdl)
            denom = tf + K1 * (1 - B + B * dl / avgdl)
            scores[s] = scores.get(s, 0.0) + idf * tf * (K1 + 1) / denom
            if script:
                scripts.setdefault(s, set()).add(script)
    if script_bonus and len({_script(t) for t in uniq} - {""}) > 1:
        for s in scores:
            scores[s] *= 1 + SCRIPT_BONUS * max(0, len(scripts.get(s, ())) - 1)
    return scores


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def default_dynamics(created: str | None = None) -> dict[str, Any]:
    dt = _parse_dt(created) or datetime.now(timezone.utc)
    return {"strength": 1.0, "stability": STABILITY_INIT,
            "access_count": 0, "last_access": dt.isoformat()}


def effective_strength(dyn: dict[str, Any], now: datetime) -> float:
    """Ebbinghaus retention: ``strength · exp(−days/stability)``, floored.

    Unparseable ``last_access`` fails open (no decay) — a note must never
    become unreachable because of a corrupt timestamp.
    """
    strength = float(dyn.get("strength", 1.0))
    last = _parse_dt(dyn.get("last_access"))
    if last is None:
        return max(EFF_FLOOR, min(strength, STRENGTH_CAP))
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    stability = max(1e-6, float(dyn.get("stability", STABILITY_INIT)))
    return max(EFF_FLOOR, strength * math.exp(-days / stability))


def potentiate(dyn: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Hebbian reinforcement on access; returns a NEW dict.

    Deviations from mempalace's +0.05/+0.1 additive constants are deliberate:
    those were tuned for edge co-occurrence, not note access. A personal
    vault sees few accesses, so strength moves in ~20 touches and stability
    grows multiplicatively (SM-2-style spaced repetition), gated on ≥1 h
    spacing (Cepeda effect) exactly like mempalace.
    """
    last = _parse_dt(dyn.get("last_access"))
    hours = ((now - last).total_seconds() / 3600.0) if last else SPACING_HOURS
    stability = float(dyn.get("stability", STABILITY_INIT))
    if hours >= SPACING_HOURS:
        stability = min(STABILITY_CAP, stability * STABILITY_GROWTH)
    return {
        "strength": min(STRENGTH_CAP,
                        float(dyn.get("strength", 1.0)) + STRENGTH_STEP),
        "stability": stability,
        "access_count": int(dyn.get("access_count", 0)) + 1,
        "last_access": now.isoformat(),
    }


def decayed_ema(ema: float, last_hit: str | None, today: date) -> float:
    """Zone EMA decayed lazily by ``0.9^days`` since it was last bumped."""
    if not last_hit:
        return float(ema)
    try:
        days = max(0, (today - date.fromisoformat(str(last_hit))).days)
    except ValueError:
        return float(ema)
    return float(ema) * (ZONE_EMA_DECAY ** days)


# -- note parsing -------------------------------------------------------------

def _note_entry(path: Path, rel: str,
                field_aware: bool = False) -> dict[str, Any] | None:
    """Parse one note file into an index entry (module-level for testability)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        st = path.stat()
    except OSError:
        return None
    meta, body = frontmatter.parse(text)
    title = str(meta.get("title") or path.stem)
    raw_tags = meta.get("tags")
    tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    try:
        confidence = float(meta.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    terms: dict[str, int] = {}
    for tok in tokenize(" ".join([title, " ".join(tags), body])):
        terms[tok] = terms.get(tok, 0) + 1
    rel = rel.replace("\\", "/")
    zone = rel.rsplit("/", 1)[0] if "/" in rel else ""
    summary = ""
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            summary = line[:120]
            break
    entry: dict[str, str | list[str] | float | int | dict[str, int]
                | dict[str, dict[str, int]] | None] = {
        "title": title, "rel": rel, "zone": zone,
        "type": str(meta.get("type", "topic")),
        "tags": tags, "links": sorted(set(WIKILINK_RE.findall(text))),
        "created": str(meta.get("created", "")),
        "updated": str(meta.get("updated", "")),
        "confidence": confidence,
        "polarity": str(meta.get("polarity") or "positive"),
        "expires_at": (str(meta["expires_at"])
                       if meta.get("expires_at") else None),
        "summary": summary,
        "mtime": st.st_mtime, "size": st.st_size,
        "doclen": _doc_length(terms), "terms": terms,
    }
    if field_aware:
        fields: dict[str, dict[str, int]] = {}
        for name, text in (("title", title), ("tags", " ".join(tags)), ("body", body)):
            frequencies: dict[str, int] = {}
            for tok in tokenize(text):
                frequencies[tok] = frequencies.get(tok, 0) + 1
            fields[name] = frequencies
        entry["field_terms"] = fields
    return entry


def _doc_length(terms: dict[str, int]) -> int:
    """BM25 document length. Single Han/kana characters are left out: they
    repeat what the CJK bigrams already count, and letting them in inflates
    the average length every note is normalised against."""
    return sum(tf for t, tf in terms.items()
               if len(t) > 1 or _script(t) != "cjk")


def _encode_index(notes: dict[str, dict[str, Any]]) -> bytes:
    """The index cache: compact UTF-8 JSON, DEFLATE-compressed (zlib level 1).
    Measured at 10k notes: 15.8 MB of plain JSON becomes 3.3 MB; a
    delta+varint posting format reached 5.5 MB with slower saves and loads."""
    raw = json.dumps({"version": INDEX_VERSION, "notes": notes},
                     separators=(",", ":"), ensure_ascii=False)
    return zlib.compress(raw.encode("utf-8"), 1)


def _decode_index(blob: bytes) -> dict[str, dict[str, Any]]:
    data = json.loads(zlib.decompress(blob))
    if data.get("version") != INDEX_VERSION:
        return {}
    notes = data.get("notes")
    return notes if isinstance(notes, dict) else {}


def _shared_ranks(ranking: list[tuple[str, float]]) -> dict[str, int]:
    """1-based ranks of a best-first (slug, score) list; equal scores share
    the rank of the first of them, so identical notes stay tied after fusion
    (decay and zone priority then decide between them)."""
    ranks: dict[str, int] = {}
    prev: float | None = None
    rank = 0
    for i, (s, score) in enumerate(ranking, 1):
        if score != prev:
            rank, prev = i, score
        ranks[s] = rank
    return ranks


def _rrf(rankings: list[list[tuple[str, float]]], k: float | None = None,
         weights: list[float] | None = None) -> dict[str, float]:
    """Reciprocal-rank fusion of best-first (slug, score) lists; ``weights``
    scales each list's vote (default 1 each)."""
    k = RRF_K if k is None else k
    fused: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights or [1.0] * len(rankings)):
        for s, rank in _shared_ranks(ranking).items():
            fused[s] = fused.get(s, 0.0) + weight / (k + rank)
    return fused


def _mostly_cjk(text: str) -> bool:
    """True when at least half of the query's letters are Han or kana."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and 2 * sum(
        1 for c in letters if _CJK_CHAR.match(c)) >= len(letters)


def _entry_expired(entry: dict[str, Any], today: date) -> bool:
    raw = entry.get("expires_at")
    if not raw:
        return False
    try:
        return date.fromisoformat(str(raw)) < today
    except ValueError:
        return False


# -- engine -------------------------------------------------------------------

class Mnemosyne:
    """Index + dynamics over one vault directory. Thread-safe via one RLock.

    Sidecar persistence is best-effort: the index is a rebuildable cache and
    dynamics are advisory telemetry, so a failed flush must never break a
    memory read/write (it self-heals on the next refresh).
    """

    def __init__(self, vault: Path, semantic: bool | None = None, *,
                 field_aware: bool = False, title_weight: float = 1.5,
                 tag_weight: float = 1.5, evidence_diversity: bool = False,
                 incremental_doclen: bool = False):
        """``semantic``: None = the core ranking, unless
        ``MNEMOSYNE_SEMANTIC=1`` asks for the optional semantic mode; True =
        request it (warns and stays on the core when it is unavailable);
        False = core only.

        ``field_aware`` enables weighted title/tag/body frequencies before
        BM25 saturation, using the existing aggregate document length. This
        is not BM25F: there is no per-field length normalization. Default
        False retains the original entries, cache format and ranking.

        ``evidence_diversity`` reorders the bounded scored pool for query
        coverage and defers lexical near-duplicates, preserving full matches.
        ``incremental_doclen`` maintains integer length/count totals on index
        mutations; full cache persistence remains unchanged. Both default
        False, and each experiment can be enabled independently."""
        if not all(math.isfinite(w) and w > 0 for w in (title_weight, tag_weight)):
            raise ValueError("field weights must be finite and positive")
        self.vault = Path(vault)
        self._semantic_mode = semantic
        self._field_aware: bool = field_aware
        self._title_weight: float = title_weight
        self._tag_weight: float = tag_weight
        self._evidence_diversity: bool = evidence_diversity
        self._incremental_doclen: bool = incremental_doclen
        self._total_doclen: int = 0
        self._doc_count: int = 0
        self._sem: Any = None
        self._lock = threading.RLock()
        self._notes: dict[str, dict[str, Any]] | None = None
        self._dyn: dict[str, Any] | None = None
        self._postings: dict[str, dict[str, int]] = {}
        self._avgdl = 0.0
        self._scanned_at: float | None = None   # _clock() of the last vault scan

    # -- persistence --------------------------------------------------------

    @property
    def _index_path(self) -> Path:
        return self.vault / INDEX_FILE

    @property
    def _dyn_path(self) -> Path:
        return self.vault / DYNAMICS_FILE

    def _load(self) -> None:
        try:
            notes = _decode_index(self._index_path.read_bytes())
        except (OSError, ValueError, zlib.error, AttributeError):
            notes = {}   # missing, older or corrupt cache: refresh() rebuilds it
        self._notes = notes
        if not self._field_aware:
            for entry in notes.values():
                entry.pop("field_terms", None)
        self._postings = {}
        for s, e in notes.items():
            self._add_postings(s, e.get("terms") or {})
        self._recompute_avgdl()

        self._load_dynamics()

    def _load_dynamics(self) -> None:
        dyn: dict[str, Any] = {"notes": {}, "zones": {}}
        try:
            raw = json.loads(self._dyn_path.read_text(encoding="utf-8"))
            if isinstance(raw.get("notes"), dict):
                dyn["notes"] = raw["notes"]
            if isinstance(raw.get("zones"), dict):
                dyn["zones"] = raw["zones"]
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        self._dyn = dyn

    def _save_index(self) -> None:
        try:
            atomic_write_bytes(self._index_path, _encode_index(self._notes or {}))
            (self.vault / LEGACY_INDEX_FILE).unlink(missing_ok=True)
        except OSError:
            pass   # cache flush is best-effort; rebuilt on next load

    def _save_dynamics(self) -> None:
        try:
            atomic_write(self._dyn_path,
                         json.dumps(self._dyn, separators=(",", ":")))
        except OSError:
            pass   # losing one access event beats failing the user's turn

    # -- postings maintenance ------------------------------------------------

    def _add_postings(self, s: str, terms: dict[str, int]) -> None:
        for t, tf in terms.items():
            self._postings.setdefault(t, {})[s] = tf

    def _drop_postings(self, s: str) -> None:
        entry = (self._notes or {}).get(s)
        for t in (entry or {}).get("terms", {}):
            post = self._postings.get(t)
            if post:
                post.pop(s, None)
                if not post:
                    del self._postings[t]

    def _recompute_avgdl(self) -> None:
        notes = self._notes or {}
        total = sum(e.get("doclen", 0) for e in notes.values())
        self._total_doclen = total
        self._doc_count = len(notes)
        self._avgdl = (total / len(notes)) if notes else 0.0

    def _adjust_doclen(self, old_length: int, new_length: int,
                       count_delta: int) -> None:
        """Update integer totals after a successful opt-in index mutation.

        Totals are derived once from cached entries on load. The unchanged
        compressed cache persists entries, not redundant floating statistics.
        Rezone changes no length; failed parsing changes no totals.
        """
        self._total_doclen += new_length - old_length
        self._doc_count += count_delta
        self._avgdl = self._total_doclen / self._doc_count if self._doc_count else 0.0

    def _read_entry(self, path: Path, rel: str) -> dict[str, Any] | None:
        """Keep the original parser call/cache unchanged when the flag is off."""
        if self._field_aware:
            return _note_entry(path, rel, field_aware=True)
        return _note_entry(path, rel)

    def _search_postings(self, terms: Iterable[str]
                         ) -> Mapping[str, Mapping[str, int | float]]:
        """Weight only query-bearing postings; IDF and length stay unchanged."""
        if not self._field_aware:
            return self._postings
        notes = self._notes or {}
        weighted: dict[str, dict[str, float]] = {}
        for term in dict.fromkeys(terms):
            weighted[term] = {}
            for s, tf in self._postings.get(term, {}).items():
                fields = notes[s]["field_terms"]
                weighted[term][s] = (
                    tf + (self._title_weight - 1) * fields["title"].get(term, 0)
                    + (self._tag_weight - 1) * fields["tags"].get(term, 0))
        return weighted

    # -- scanning / refreshing ------------------------------------------------

    def _scan(self) -> dict[str, tuple[str, float, int]]:
        """slug -> (rel, mtime, size) for every .md at root + one zone level.

        Duplicate slugs across zones keep the newest file (shouldn't happen
        through the library's own write path, but a user can hand-copy files)."""
        out: dict[str, tuple[str, float, int]] = {}

        def add(name: str, full: str, rel: str) -> None:
            if not name.endswith(".md"):
                return
            try:
                st = os.stat(full)
            except OSError:
                return
            s = name[:-3]
            cur = out.get(s)
            if cur is None or st.st_mtime > cur[1]:
                out[s] = (rel, st.st_mtime, st.st_size)

        try:
            top = list(os.scandir(self.vault))
        except OSError:
            return out
        for e in top:
            if e.name.startswith("."):
                continue
            if e.is_file():
                add(e.name, e.path, e.name)
            elif e.is_dir():
                try:
                    sub = list(os.scandir(e.path))
                except OSError:
                    continue
                for f in sub:
                    if f.is_file():
                        add(f.name, f.path, f"{e.name}/{f.name}")
        return out

    def refresh(self) -> None:
        """Bring the index up to date by stat fingerprints; re-parse only
        changed files. Always scans: call it to see a note edited outside
        the library (e.g. in Obsidian) at once. ``search`` alone scans at
        most once per ``SCAN_TTL`` seconds, because the stat pass is most of
        a search at 10k notes (about 37 of 43 ms)."""
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None
            scan = self._scan()
            self._scanned_at = _clock()
            changed = False
            for s in [s for s in self._notes if s not in scan]:
                if self._incremental_doclen:
                    self._adjust_doclen(self._notes[s].get("doclen", 0), 0, -1)
                self._drop_postings(s)
                del self._notes[s]
                changed = True
            for s, (rel, mtime, size) in scan.items():
                e = self._notes.get(s)
                if (e and e.get("rel") == rel and e.get("mtime") == mtime
                        and e.get("size") == size
                        and (not self._field_aware or "field_terms" in e)):
                    continue
                entry = self._read_entry(self.vault / rel, rel)
                if entry is None:
                    continue
                if e:
                    self._drop_postings(s)
                if self._incremental_doclen:
                    self._adjust_doclen(
                        e.get("doclen", 0) if e else 0, entry["doclen"], int(e is None))
                self._notes[s] = entry
                self._add_postings(s, entry["terms"])
                changed = True
            if changed:
                if not self._incremental_doclen:
                    self._recompute_avgdl()
                self._save_index()

    def rebuild(self) -> dict[str, int]:
        """Discard the cache, rescan everything, return stats."""
        with self._lock:
            if self._dyn is None:
                self._load_dynamics()   # skip parsing the index we discard
            self._notes = {}
            self._postings = {}
            if self._incremental_doclen:
                self._total_doclen = self._doc_count = 0
                self._avgdl = 0.0
            self.refresh()
            return self.stats()

    def note_written(self, path: Path) -> None:
        """Targeted index update after the caller wrote one note file."""
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None
            try:
                rel = path.relative_to(self.vault).as_posix()
            except ValueError:
                return
            entry = self._read_entry(path, rel)
            if entry is None:
                return
            s = path.stem
            old = self._notes.get(s)
            if s in self._notes:
                self._drop_postings(s)
            if self._incremental_doclen:
                self._adjust_doclen(
                    old.get("doclen", 0) if old else 0, entry["doclen"], int(old is None))
            self._notes[s] = entry
            self._add_postings(s, entry["terms"])
            if not self._incremental_doclen:
                self._recompute_avgdl()
            self._save_index()

    # -- accessors -------------------------------------------------------------

    def entries(self) -> dict[str, dict[str, Any]]:
        """A snapshot copy of all index entries. Callers iterate this while
        other threads may refresh/rezone, so never hand out the live dict
        (entry dicts themselves are replaced, not mutated, on update)."""
        with self._lock:
            self.refresh()
            return dict(self._notes or {})

    def note_meta(self, s: str) -> dict[str, Any] | None:
        with self._lock:
            self.refresh()
            e = (self._notes or {}).get(s)
            return dict(e) if e else None

    def resolve_rel(self, s: str) -> str | None:
        with self._lock:
            self.refresh()
            e = (self._notes or {}).get(s)
            return e["rel"] if e else None

    def dynamics_of(self, s: str) -> dict[str, Any]:
        with self._lock:
            if self._dyn is None:
                self._load()
            assert self._dyn is not None
            dyn = self._dyn["notes"].get(s)
            if dyn:
                return dict(dyn)
            e = (self._notes or {}).get(s) or {}
            return default_dynamics(e.get("created") or None)

    def set_dynamics(self, s: str, dyn: dict[str, Any]) -> None:
        """Overwrite one note's dynamics (maintenance/test seam)."""
        with self._lock:
            if self._dyn is None:
                self._load()
            assert self._dyn is not None
            self._dyn["notes"][s] = dict(dyn)
            self._save_dynamics()

    def effective_of(self, s: str, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return effective_strength(self.dynamics_of(s), now)

    # -- dynamics recording ------------------------------------------------------

    def record_access(self, s: str, now: datetime | None = None) -> None:
        """Potentiate a note + bump its zone EMA. Unknown slugs are a no-op."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None and self._dyn is not None
            e = self._notes.get(s)
            if e is None:
                self.refresh()
                e = self._notes.get(s)
                if e is None:
                    return
            self._dyn["notes"][s] = potentiate(self.dynamics_of(s), now)
            z = e["zone"]
            zs = self._dyn["zones"].get(z) or {}
            today = now.date()
            ema = decayed_ema(float(zs.get("ema", 0.0)),
                              zs.get("last_hit"), today) + 1.0
            self._dyn["zones"][z] = {"ema": ema,
                                     "last_hit": today.isoformat()}
            self._save_dynamics()

    def zone_priorities(self, today: date | None = None) -> dict[str, float]:
        """Normalized [0,1] priority per zone present in the vault."""
        # Default matches every caller (UTC-derived), so an argless call can't
        # silently diverge from the rest of the dynamics system.
        today = today or datetime.now(timezone.utc).date()
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None and self._dyn is not None
            zones = {e["zone"] for e in self._notes.values()}
            raw: dict[str, float] = {}
            for z in zones:
                zs = self._dyn["zones"].get(z) or {}
                raw[z] = decayed_ema(float(zs.get("ema", 0.0)),
                                     zs.get("last_hit"), today)
            mx = max(raw.values(), default=0.0)
            return {z: (v / mx if mx > 0 else 0.0) for z, v in raw.items()}

    # -- retrieval ------------------------------------------------------------

    def _semantic_index(self) -> Any:
        """The SemanticIndex, or None when disabled/unavailable (decided once)."""
        if self._sem is None:
            from . import semantic

            want = self._semantic_mode
            if want is None:           # opt-in: the default is the core ranking
                want = bool(semantic.enabled_by_env())
            if not want:
                self._sem = False
            elif not semantic.available():
                log.warning("semantic search requested but the [semantic] "
                            "extra is not installed; using BM25 only")
                self._sem = False
            else:
                self._sem = semantic.SemanticIndex(self.vault)
        return self._sem or None

    def _semantic_ranking(self, query: str) -> list[tuple[str, float]]:
        sem = self._semantic_index()
        if sem is None:
            return []
        try:
            sem.sync(self.entries())
            return sem.search(query, FUSE_DEPTH)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            # model download/load or encoding failed: keep serving BM25
            log.warning("semantic search disabled for this session: %s", exc)
            self._sem = False
            return []

    def _covering(self, query: str, terms: list[str],
                  bm_list: list[tuple[str, float]]) -> list[str]:
        """Notes of the lexical leg that match every original unit of the
        query, best first. Stems, and the single characters of a longer
        Han/kana run, are derived from other units, so they do not count; a
        Han/kana character that stands alone in the query does."""
        norm = unicodedata.normalize("NFKC", query).casefold()
        alone = {cjk for cjk, _, _ in _RUN_RE.findall(norm) if len(cjk) == 1}
        posts = [self._postings.get(t, {}) for t in set(terms)
                 if not t.endswith(STEM_MARK)
                 and (len(t) > 1 or _script(t) != "cjk" or t in alone)]
        if not posts:
            return []
        return [s for s, _ in bm_list if all(s in post for post in posts)]

    def _diverse_hits(self, query: str, terms: list[str],
                      hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reorder the bounded pool, never delete candidates or change scores.

        Complete original-unit matches keep their scored order first. The
        remainder prefers uncovered informative query tokens, with original
        rank as tie-break. Lexical Jaccard >= 0.9 duplicates are deferred to
        the tail, annotated ``diversity_deferred="near_duplicate"``. Similar
        notes may contradict one another: this is selection, not truth or
        a deduplication decision. No semantic/vector threshold is used.
        """
        notes = self._notes or {}
        tokens = {
            h["slug"]: {t for t in notes[h["slug"]]["terms"]
                        if not t.endswith(STEM_MARK)
                        and (len(t) > 1 or _script(t) != "cjk")}
            for h in hits
        }
        query_tokens = {t for t in terms if not t.endswith(STEM_MARK)
                        and (len(t) > 1 or _script(t) != "cjk")}
        protected = set(self._covering(
            query, terms, [(h["slug"], h["score"]) for h in hits]))
        selected = [h for h in hits if h["slug"] in protected]
        remaining = [h for h in hits if h["slug"] not in protected]
        covered: set[str] = set()
        for h in selected:
            covered.update(tokens[h["slug"]] & query_tokens)
        deferred: list[dict[str, Any]] = []
        while remaining:
            distinct: list[dict[str, Any]] = []
            for h in remaining:
                current = tokens[h["slug"]]
                duplicate = any(
                    len(current & tokens[p["slug"]]) / len(current | tokens[p["slug"]])
                    >= DIVERSITY_JACCARD
                    for p in selected if current | tokens[p["slug"]])
                if duplicate:
                    deferred.append({**h, "diversity_deferred": "near_duplicate"})
                else:
                    distinct.append(h)
            if not distinct:
                break
            # max keeps the first tied item: the score/updated order above.
            pick = max(distinct, key=lambda h: len(
                (tokens[h["slug"]] & query_tokens) - covered))
            selected.append(pick)
            covered.update(tokens[pick["slug"]] & query_tokens)
            remaining = [h for h in distinct if h["slug"] != pick["slug"]]
        return selected + deferred

    def search(self, query: str, limit: int = 8, zone: str | None = None,
               include_archive: bool = False,
               now: datetime | None = None,
               expansions: Mapping[str, Any] | None = None
               ) -> list[dict[str, Any]]:
        """BM25 × (1 + W_DYN·eff/cap + W_ZONE·zone priority), index-only.

        ``expansions`` widens the query at search time without touching the
        index: a caller that can paraphrase (the host model) passes
        ``{"synonyms": [...], "keywords": [...], "related": [...],
        "note_line": "..."}`` and each added term scores as BM25 scaled by its
        tier's ``EXPANSION_WEIGHTS``, below the query's own words. A note that
        holds every original unit of the query stays ahead of the notes only
        an expansion found. ``None`` ranks exactly as before.

        With the semantic leg active, the score is a reciprocal-rank fusion
        of two rankings (top ``FUSE_DEPTH`` of each): the lexical one above,
        boosts included, and the semantic one weighted by ``SEM_WEIGHT``
        (``SEM_WEIGHT_CJK`` for queries written mostly in Han/kana). Notes
        that contain every original unit of the query keep their lexical
        order ahead of everything else, so an exact keyword lookup returns
        what the core returns.

        The vault is re-scanned for outside edits at most once per
        ``SCAN_TTL`` seconds; notes written through the library are indexed
        by ``note_written`` and never wait. ``refresh()`` forces a scan."""
        with self._lock:
            if (self._notes is None or self._scanned_at is None
                    or _clock() - self._scanned_at >= SCAN_TTL):
                self.refresh()
        now = now or datetime.now(timezone.utc)
        terms = tokenize(query)
        added = expansion_weights(expansions, terms) if expansions else {}
        sem_ranked = self._semantic_ranking(query) if query.strip() else []
        with self._lock:
            notes = self._notes or {}
            if not notes or not (terms or sem_ranked):
                return []
            doclens = {s: e.get("doclen", 0) for s, e in notes.items()}
            postings = self._search_postings([*terms, *added])
            literal = bm25_scores(terms, postings, doclens,
                                  self._avgdl, len(notes))
            pri = self.zone_priorities(today=now.date())
            # TTL is a user-facing calendar date -> LOCAL today, matching
            # memory._is_expired (render/list/purge) so no path disagrees.
            expiry_today = date.today()

            def boost(s: str) -> float:
                eff = effective_strength(self.dynamics_of(s), now)
                return (1 + W_DYN * eff / STRENGTH_CAP
                        + W_ZONE * pri.get(notes[s]["zone"], 0.0))

            def visible(s: str) -> bool:
                e = notes[s]
                if _entry_expired(e, expiry_today):
                    return False
                if zone is not None:
                    return e["zone"] == zone
                return e["zone"] != ARCHIVE_ZONE or include_archive

            def fuse(lexical: dict[str, float]) -> tuple[
                    dict[str, float], dict[str, int], list[str]]:
                """(fused scores, lexical ranks, notes that hold every
                original unit of the query) for one lexical scoring."""
                # The lexical leg is ranked the way the core ranks (usage and
                # zone boosts included) and nothing multiplies the fused score:
                # reciprocal ranks sit so close together (1/6 vs 1/7) that a
                # boost applied after fusion would reorder them at will.
                top = sorted(lexical.items(), key=lambda kv: kv[1],
                             reverse=True)[:FUSE_DEPTH]
                # equal scores fall back to the newer note, as in the core
                bm_list = sorted(((s, v * boost(s)) for s, v in top),
                                 key=lambda kv: (kv[1], notes[kv[0]]["updated"]),
                                 reverse=True)
                fused = _rrf(
                    [bm_list, [(s, v) for s, v in sem_ranked if s in notes]],
                    weights=[1.0, SEM_WEIGHT_CJK if _mostly_cjk(query) else SEM_WEIGHT])
                # notes that hold every original unit of the query stay first,
                # in lexical order; fusion orders everything after them
                covering = self._covering(query, terms, bm_list)
                top_fused = max(fused.values(), default=0.0)
                for i, s in enumerate(covering):
                    fused[s] = top_fused + len(covering) - i
                return fused, _shared_ranks(bm_list), covering

            # Notes that hold every original unit of the query ("full") take
            # no expansion score and keep the score the core gives them, so an
            # exact keyword lookup returns what it returns without expansions.
            base = literal
            full: list[str] = []
            if added:
                full = self._covering(query, terms, sorted(
                    literal.items(), key=lambda kv: kv[1],
                    reverse=True)[:FUSE_DEPTH])
                base = dict(literal)
                for s, v in bm25_scores(list(added), postings, doclens,
                                        self._avgdl, len(notes), weights=added,
                                        script_bonus=False).items():
                    if s not in full:
                        base[s] = base.get(s, 0.0) + v
            bm_order: dict[str, int] = {}
            if sem_ranked:
                base, bm_order, _ = fuse(base)
                if added:
                    core, _, full = fuse(literal)
                    for s in full:
                        base[s] = core[s]
            # Only a note this search can return is moved to the front: a full
            # match in another zone, archived or expired must not take a
            # candidate slot from a note the core would have returned.
            pinned = frozenset(s for s in full if visible(s))
            unranked = len(bm_order) + 1
            # fused ties (a note first in one leg only) go to BM25's pick
            cands = sorted(base.items(), key=lambda kv: (
                kv[0] not in pinned, -kv[1],
                bm_order.get(kv[0], unranked)))[:CAND]
            hits: list[dict[str, Any]] = []
            for s, bm in cands:
                if not visible(s):
                    continue
                e = notes[s]
                score = bm if sem_ranked else bm * boost(s)
                hits.append({"slug": s, "title": e["title"], "zone": e["zone"],
                             "rel": e["rel"], "type": e["type"],
                             "summary": e["summary"], "links": e["links"],
                             "polarity": e["polarity"], "score": score,
                             "updated": e["updated"]})
            hits.sort(key=lambda h: (h["slug"] in pinned, h["score"],
                                     -bm_order.get(h["slug"], unranked),
                                     h["updated"]), reverse=True)
            if self._evidence_diversity:
                hits = self._diverse_hits(query, terms, hits)
            return hits[:limit]

    def related(self, s: str, limit: int = RELATED_LIMIT) -> list[dict[str, Any]]:
        """Mechanical link candidates for one note (A-MEM step 1): BM25 with
        the note's own top terms, excluding itself and already-linked notes.
        The LLM (Morpheus) judges which candidates become real links."""
        e = self.note_meta(s)
        if e is None:
            return []
        top_terms = [t for t, _ in sorted(((t, n) for t, n in e.get("terms", {}).items()
                                           if not t.endswith(STEM_MARK)),
                                          key=lambda kv: kv[1], reverse=True)
                     [:RELATED_QUERY_TERMS]]
        linked = {slug(t) for t in e.get("links", [])} | {s}
        hits = self.search(" ".join(top_terms), limit=limit + len(linked))
        return [h for h in hits if h["slug"] not in linked][:limit]

    def stale(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Notes past the archive tier (eff < STALE_EFF and unused >
        STALE_DAYS). ``identity`` never goes stale (it is the always-rendered
        L0 and render does not count as access); ``_archive`` already is."""
        now = now or datetime.now(timezone.utc)
        today = now.date()
        out: list[dict[str, Any]] = []
        for s, e in self.entries().items():
            if e["zone"] in (ARCHIVE_ZONE, IDENTITY_ZONE):
                continue
            if _entry_expired(e, today):
                continue
            dyn = self.dynamics_of(s)
            last = _parse_dt(dyn.get("last_access"))
            if last is None:
                continue
            days = (now - last).total_seconds() / 86400.0
            eff = effective_strength(dyn, now)
            if eff < STALE_EFF and days > STALE_DAYS:
                out.append({"slug": s, "title": e["title"], "zone": e["zone"],
                            "last_access": dyn.get("last_access", ""),
                            "eff": eff})
        out.sort(key=lambda x: x["last_access"])
        return out

    # -- placement ------------------------------------------------------------

    def rezone(self, s: str, zone: str) -> Path:
        """Move a note into another zone directory and update the index.

        ``zone`` may be a normal zone name, ``"_archive"``, or ``""``/
        ``"inbox"`` for the vault root. Raises ValueError on unknown notes,
        invalid names, or the zone cap."""
        z = "" if zone in ("", "inbox") else str(zone)
        if z and z != ARCHIVE_ZONE and not ZONE_RE.fullmatch(z):
            raise ValueError(f"invalid zone name {zone!r} "
                             "(want ^[a-z0-9][a-z0-9-]{{0,31}}$)")
        from .vault_lock import VaultLock

        with VaultLock(self.vault).hold(), self._lock:
            self.refresh()
            assert self._notes is not None
            e = self._notes.get(s)
            if e is None:
                raise ValueError(f"no note with slug {s!r}")
            existing = {en["zone"] for en in self._notes.values()
                        if en["zone"] and en["zone"] != ARCHIVE_ZONE}
            if (z and z != ARCHIVE_ZONE and z not in existing
                    and len(existing) >= MAX_ZONES):
                raise ValueError(f"zone cap reached ({MAX_ZONES}); "
                                 "re-use an existing zone")
            old = self.vault / e["rel"]
            new_dir = (self.vault / z) if z else self.vault
            new = new_dir / f"{s}.md"
            if old != new:
                new_dir.mkdir(parents=True, exist_ok=True)
                os.replace(old, new)
            rel = f"{z}/{s}.md" if z else f"{s}.md"
            try:
                st = new.stat()
                mtime, size = st.st_mtime, st.st_size
            except OSError:
                mtime, size = e["mtime"], e["size"]
            self._notes[s] = {**e, "rel": rel, "zone": z,
                              "mtime": mtime, "size": size}
            self._save_index()
            return new

    # -- stats ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._lock:
            notes = self._notes or {}
            zones = {e["zone"] or "inbox" for e in notes.values()}
            return {"notes": len(notes), "zones": len(zones),
                    "terms": len(self._postings), "stale": len(self.stale())}
