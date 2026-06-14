from __future__ import annotations

import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.hybrid_retriever import hybrid_search


def main():
    print("=== 测试混合检索 ===")
    print()

    print("1. 语义查询：大理洱海日落")
    results = hybrid_search("大理洱海日落", top_k=3)
    for i, r in enumerate(results, 1):
        text_preview = r["text"][:50] + "..." if len(r["text"]) > 50 else r["text"]
        print(f"  {i}. [{r['title']}] {text_preview}")
        print(f"     RRF Score: {r.get('rrf_score', 'N/A')}")
    print()

    print("2. 精确查询：门票价格")
    results = hybrid_search("门票价格", top_k=3)
    for i, r in enumerate(results, 1):
        text_preview = r["text"][:50] + "..." if len(r["text"]) > 50 else r["text"]
        print(f"  {i}. [{r['title']}] {text_preview}")
        print(f"     RRF Score: {r.get('rrf_score', 'N/A')}")
    print()

    print("3. 测试加权融合：美食推荐")
    results = hybrid_search("美食推荐", top_k=3, fusion_method="weighted")
    for i, r in enumerate(results, 1):
        text_preview = r["text"][:50] + "..." if len(r["text"]) > 50 else r["text"]
        print(f"  {i}. [{r['title']}] {text_preview}")
        print(f"     Hybrid Score: {r.get('hybrid_score', 'N/A')}")
    print()

    print("=== 测试完成 ===")


if __name__ == "__main__":
    main()