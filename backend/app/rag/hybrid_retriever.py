from __future__ import annotations

import logging
from typing import List, Dict, Any

from app.rag.vector_db import search_guide_chunks as vector_search
from app.rag.bm25_index import search_guide_chunks_by_bm25 as bm25_search
from app.services.cache_service import get_cached_json, set_cached_json
from app.config import REDIS_RAG_TTL_SECONDS

logger = logging.getLogger(__name__)


def _normalize_cache_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_scores(scores: List[float]) -> List[float]:
    if not scores:
        return []
    min_score = min(scores)
    max_score = max(scores)
    if max_score == min_score:
        return [0.5] * len(scores)
    return [(s - min_score) / (max_score - min_score) for s in scores]


def _get_doc_key(result: Dict[str, Any]) -> str:
    return f"{result['source']}:{result['title']}:{result['text'][:50]}"


def _fuse_results_with_rrf(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    doc_ranks: Dict[str, List[int]] = {}

    for rank, result in enumerate(vector_results, 1):
        key = _get_doc_key(result)
        doc_ranks.setdefault(key, [0, 0])[0] = rank

    for rank, result in enumerate(bm25_results, 1):
        key = _get_doc_key(result)
        doc_ranks.setdefault(key, [0, 0])[1] = rank

    all_results = {_get_doc_key(r): r for r in vector_results + bm25_results}

    fused_scores: List[Dict[str, Any]] = []
    for doc_key, (v_rank, b_rank) in doc_ranks.items():
        score = 0.0
        if v_rank > 0:
            score += 1 / (k + v_rank)
        if b_rank > 0:
            score += 1 / (k + b_rank)

        result = all_results[doc_key].copy()
        result["rrf_score"] = round(score, 6)
        result["vector_rank"] = v_rank
        result["bm25_rank"] = b_rank
        fused_scores.append(result)

    fused_scores.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused_scores


def _fuse_results_with_weighted(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> List[Dict[str, Any]]:
    vector_scores = [r.get("distance", 1 - r.get("similarity", 0)) for r in vector_results]
    bm25_scores = [r.get("bm25_score", 0) for r in bm25_results]

    vector_normalized = _normalize_scores(vector_scores)
    bm25_normalized = _normalize_scores(bm25_scores)

    doc_scores: Dict[str, float] = {}
    doc_map: Dict[str, Dict[str, Any]] = {}

    for i, result in enumerate(vector_results):
        key = _get_doc_key(result)
        doc_map[key] = result.copy()
        doc_scores[key] = vector_weight * vector_normalized[i]

    for i, result in enumerate(bm25_results):
        key = _get_doc_key(result)
        if key not in doc_map:
            doc_map[key] = result.copy()
        doc_scores[key] = doc_scores.get(key, 0) + bm25_weight * bm25_normalized[i]

    fused = [
        {**doc_map[key], "hybrid_score": round(doc_scores[key], 4)}
        for key in sorted(doc_scores.keys(), key=lambda k: doc_scores[k], reverse=True)
    ]
    return fused


def hybrid_search(
    query: str,
    top_k: int = 3,
    fusion_method: str = "rrf",
    **kwargs,
) -> List[Dict[str, Any]]:
    cache_key = f"hybrid:{_normalize_cache_text(query)}:{top_k}:{fusion_method}"
    cached = get_cached_json(cache_key)
    if cached is not None:
        logger.info("hybrid cache hit: query=%s", query)
        return cached

    logger.info("hybrid cache miss: query=%s", query)

    candidate_k = max(top_k * 2, 6)
    vector_results = vector_search(query, candidate_k)
    bm25_results = bm25_search(query, candidate_k)

    logger.debug("vector results: %d, bm25 results: %d", len(vector_results), len(bm25_results))

    if fusion_method == "rrf":
        fused = _fuse_results_with_rrf(
            vector_results,
            bm25_results,
            k=kwargs.get("rrf_k", 60)
        )
    else:
        fused = _fuse_results_with_weighted(
            vector_results,
            bm25_results,
            vector_weight=kwargs.get("vector_weight", 0.6),
            bm25_weight=kwargs.get("bm25_weight", 0.4),
        )

    final_results = fused[:top_k]
    set_cached_json(cache_key, final_results, expire_seconds=REDIS_RAG_TTL_SECONDS)

    return final_results