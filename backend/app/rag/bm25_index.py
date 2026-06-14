from __future__ import annotations

import json
import os
from pathlib import Path
from rank_bm25 import BM25Okapi
from app.config import BACKEND_DIR

BM25_INDEX_DIR = BACKEND_DIR / "db" / "bm25_index"


class BM25Index:
    def __init__(self):
        self.bm25 = None
        self.documents = []
        self.metadata = []
        self._load_index()

    def _tokenize(self, text: str) -> list[str]:
        import re
        tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+|\d+', text)
        return [t.lower() for t in tokens if t.strip()]

    def _build_index(self, chunks: list[dict[str, str]]):
        self.documents = [chunk["text"] for chunk in chunks]
        self.metadata = [{"title": chunk["title"], "source": chunk["source"]} for chunk in chunks]
        tokenized_docs = [self._tokenize(doc) for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_docs)

    def _save_index(self):
        BM25_INDEX_DIR.mkdir(parents=True, exist_ok=True)
        index_data = {
            "documents": self.documents,
            "metadata": self.metadata,
        }
        with open(BM25_INDEX_DIR / "index.json", "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False)

    def _load_index(self):
        index_file = BM25_INDEX_DIR / "index.json"
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)
            self.documents = index_data["documents"]
            self.metadata = index_data["metadata"]
            tokenized_docs = [self._tokenize(doc) for doc in self.documents]
            self.bm25 = BM25Okapi(tokenized_docs)

    def build_from_chunks(self, chunks: list[dict[str, str]]):
        self._build_index(chunks)
        self._save_index()

    def query(self, query: str, top_k: int = 3) -> list[dict[str, str]]:
        if self.bm25 is None or not self.documents:
            return []
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        scored_indices = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        results = []
        for idx, score in scored_indices:
            if score > 0:
                results.append({
                    "title": self.metadata[idx]["title"],
                    "text": self.documents[idx],
                    "source": self.metadata[idx]["source"],
                    "bm25_score": round(score, 4),
                })
        return results


_bm25_index: BM25Index | None = None


def get_bm25_index() -> BM25Index:
    global _bm25_index
    if _bm25_index is None:
        _bm25_index = BM25Index()
    return _bm25_index


def search_guide_chunks_by_bm25(query: str, top_k: int = 3) -> list[dict[str, str]]:
    index = get_bm25_index()
    return index.query(query, top_k)