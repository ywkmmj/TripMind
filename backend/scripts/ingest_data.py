from __future__ import annotations

import argparse
from pathlib import Path
import sys


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import CHROMA_COLLECTION_NAME, CHROMA_DB_DIR, EMBEDDING_MODEL
from app.rag.vector_db import ingest_guide_chunks_to_chroma, load_guide_chunks
from app.rag.bm25_index import get_bm25_index


def main() -> int:
    chunks = load_guide_chunks()
    print("=== 准备写入索引 ===")
    print(f"chunk_count: {len(chunks)}")
    print(f"embedding_model: {EMBEDDING_MODEL}")
    print(f"chroma_db_dir: {CHROMA_DB_DIR}")
    print(f"collection_name: {CHROMA_COLLECTION_NAME}")
    print()

    print("=== 写入 Chroma 向量库 ===")
    written_count = ingest_guide_chunks_to_chroma()
    print(f"written_count (Chroma): {written_count}")
    print()

    print("=== 构建 BM25 索引 ===")
    bm25_index = get_bm25_index()
    bm25_index.build_from_chunks(chunks)
    print(f"written_count (BM25): {len(chunks)}")
    print()

    print("=== 写入完成 ===")
    return 0


def sync_ugc() -> int:
    """同步 UGC 内容到知识库"""
    import asyncio
    from app.scripts.sync_knowledge_base import sync_platform

    print("=== 同步 UGC 内容 ===")
    print("提示：使用 python -m app.scripts.sync_knowledge_base sync 命令进行更完整的同步")
    print()

    async def _run():
        result = await sync_platform(
            platform="xiaohongshu",
            keyword="旅行",
            destination=None,
            limit=20,
            quality_threshold=60.0,
        )
        return result

    result = asyncio.run(_run())
    print(f"同步结果: {result}")
    return 0


if __name__ == "__main__":
    import sys

    # 检查是否有 --sync-ugc 参数
    if "--sync-ugc" in sys.argv:
        sys.argv.remove("--sync-ugc")
        raise SystemExit(sync_ugc())

    raise SystemExit(main())
