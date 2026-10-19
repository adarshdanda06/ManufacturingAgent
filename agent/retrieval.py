"""Failure library retrieval.

Given a free-text summary of observed symptoms, return the top-k historical
failure records. Retrievers share the ``Retriever`` protocol so the agent does
not care which one is used. Two lexical implementations are provided (TF-IDF
cosine and BM25), both pure Python with no model downloads or paid APIs.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

LIBRARY_PATH = Path(__file__).with_name("failure_library.json")

_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have in into is it its of on or so than that the
    then there these this to was were when which while with about after all also any been both can
    do does each few more most no not only other our out over same some such too very what where who
    why will would one two three four per""".split()
)

# A few domain synonyms so technician wording and test-output wording meet.
_SYNONYMS = {
    "amps": "current",
    "amp": "current",
    "draw": "current",
    "draws": "current",
    "hot": "temperature",
    "overheats": "temperature",
    "overheating": "temperature",
    "temp": "temperature",
    "speed": "rpm",
    "dropouts": "dropped",
    "dropout": "dropped",
    "drops": "dropped",
    "sag": "sags",
    "sagging": "sags",
    "imbalanced": "imbalance",
    "unbalanced": "imbalance",
    "fps": "frame",
    "framerate": "frame",
    "desync": "sync",
    "termination": "terminator",
    "ohms": "ohm",
}


def _stem(tok: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


def tokenize(text: str) -> list[str]:
    """Lowercase, split, drop stopwords and bare numbers, stem, add bigrams."""
    raw = re.findall(r"[a-z][a-z0-9_]*", text.lower())
    words: list[str] = []
    for w in raw:
        for part in w.split("_"):
            if not part or part in _STOPWORDS:
                continue
            words.append(_stem(_SYNONYMS.get(part, part)))
    bigrams = [f"{a}__{b}" for a, b in zip(words, words[1:])]
    return words + bigrams


@dataclass(frozen=True)
class FailureRecord:
    """One historical root-cause record."""

    id: str
    title: str
    subsystem: str
    symptom_summary: str
    key_tests: tuple[str, ...]
    root_cause_code: str
    root_cause: str
    rework_action: str | None
    rework_notes: str
    occurrences: int

    def index_text(self) -> str:
        """Text the retrievers index: what a technician would search against.

        ``key_tests`` is deliberately left out. Test names show up in queries
        for tests that passed too, and lexical scoring cannot tell the
        difference, so indexing them rewards records with long test lists.
        """
        return " ".join([self.title, self.subsystem, self.symptom_summary])

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation for tool output and traces."""
        return {
            "id": self.id,
            "title": self.title,
            "subsystem": self.subsystem,
            "symptom_summary": self.symptom_summary,
            "key_tests": list(self.key_tests),
            "root_cause_code": self.root_cause_code,
            "root_cause": self.root_cause,
            "rework_action": self.rework_action,
            "rework_notes": self.rework_notes,
            "occurrences": self.occurrences,
        }


@dataclass(frozen=True)
class Match:
    """A retrieved record and its similarity score."""

    record: FailureRecord
    score: float


def load_library(path: Path | str = LIBRARY_PATH) -> list[FailureRecord]:
    """Load failure records from JSON."""
    data = json.loads(Path(path).read_text())
    return [
        FailureRecord(
            id=r["id"],
            title=r["title"],
            subsystem=r["subsystem"],
            symptom_summary=r["symptom_summary"],
            key_tests=tuple(r["key_tests"]),
            root_cause_code=r["root_cause_code"],
            root_cause=r["root_cause"],
            rework_action=r["rework_action"],
            rework_notes=r["rework_notes"],
            occurrences=int(r["occurrences"]),
        )
        for r in data["records"]
    ]


class Retriever(Protocol):
    """Anything that can rank failure records against a symptom description."""

    name: str

    def search(self, query: str, k: int = 3) -> list[Match]:
        """Return up to ``k`` matches with positive score, best first."""
        ...


class TfidfRetriever:
    """TF-IDF with sublinear term frequency and cosine similarity."""

    name = "tfidf"

    def __init__(self, records: list[FailureRecord]) -> None:
        self.records = records
        docs = [Counter(tokenize(r.index_text())) for r in records]
        n = len(docs)
        df: Counter[str] = Counter()
        for d in docs:
            df.update(d.keys())
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.doc_vecs = [self._vec(d) for d in docs]

    def _vec(self, counts: Counter[str]) -> dict[str, float]:
        v = {t: (1.0 + math.log(c)) * self.idf[t] for t, c in counts.items() if t in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def search(self, query: str, k: int = 3) -> list[Match]:
        q = self._vec(Counter(tokenize(query)))
        scored = []
        for rec, dv in zip(self.records, self.doc_vecs):
            s = sum(w * dv.get(t, 0.0) for t, w in q.items())
            if s > 0:
                scored.append(Match(rec, round(s, 4)))
        scored.sort(key=lambda m: (-m.score, m.record.id))
        return scored[:k]


class Bm25Retriever:
    """Okapi BM25 over the same tokenization."""

    name = "bm25"

    def __init__(self, records: list[FailureRecord], k1: float = 1.4, b: float = 0.75) -> None:
        self.records = records
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(r.index_text())) for r in records]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lens) / max(1, len(self.lens))
        n = len(self.docs)
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query: str, k: int = 3) -> list[Match]:
        q = set(tokenize(query))
        scored = []
        for rec, d, dl in zip(self.records, self.docs, self.lens):
            s = 0.0
            for t in q:
                f = d.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg_len))
            if s > 0:
                scored.append(Match(rec, round(s, 4)))
        scored.sort(key=lambda m: (-m.score, m.record.id))
        return scored[:k]


RETRIEVERS: dict[str, type[TfidfRetriever] | type[Bm25Retriever]] = {
    "tfidf": TfidfRetriever,
    "bm25": Bm25Retriever,
}


def get_retriever(name: str = "bm25", path: Path | str = LIBRARY_PATH) -> Retriever:
    """Build a retriever by name over the library at ``path``.

    Raises:
        KeyError: if ``name`` is not a registered retriever.
    """
    return RETRIEVERS[name](load_library(path))
