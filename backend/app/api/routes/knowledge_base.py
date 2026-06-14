"""
知识库管理 API 路由

提供 UGC 内容管理和检索接口。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.knowledge_base.collectors.xiaohongshu_collector import XiaohongshuCollector
from app.knowledge_base.parsers.multimodal_parser import MultimodalParser
from app.knowledge_base.processors.quality_scorer import QualityScorer
from app.knowledge_base.storage.kb_manager import KnowledgeBaseManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kb", tags=["knowledge_base"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class SyncRequest(BaseModel):
    """同步请求"""
    platform: str = "xiaohongshu"
    keyword: str = "旅行"
    destination: str | None = None
    limit: int = 20


class SyncResponse(BaseModel):
    """同步响应"""
    message: str
    collected: int
    processed: int
    ingested: int
    skipped: int
    failed: int


class StatsResponse(BaseModel):
    """统计信息响应"""
    collector: dict[str, Any]
    knowledge_base: dict[str, Any]


class SearchRequest(BaseModel):
    """搜索请求"""
    query: str
    destination: str | None = None
    top_k: int = 5


class SearchResponse(BaseModel):
    """搜索响应"""
    results: list[dict[str, Any]]
    total: int


# ============================================================================
# 依赖实例
# ============================================================================

_collector: XiaohongshuCollector | None = None
_parser: MultimodalParser | None = None
_scorer: QualityScorer | None = None
_kb_manager: KnowledgeBaseManager | None = None


def get_collector() -> XiaohongshuCollector:
    """获取采集器实例"""
    global _collector
    if _collector is None:
        _collector = XiaohongshuCollector()
    return _collector


def get_parser() -> MultimodalParser:
    """获取解析器实例"""
    global _parser
    if _parser is None:
        _parser = MultimodalParser()
    return _parser


def get_scorer() -> QualityScorer:
    """获取评分器实例"""
    global _scorer
    if _scorer is None:
        _scorer = QualityScorer()
    return _scorer


def get_kb_manager() -> KnowledgeBaseManager:
    """获取知识库管理器实例"""
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager


# ============================================================================
# API 路由
# ============================================================================

@router.post("/sync", response_model=SyncResponse)
async def sync_knowledge_base(request: SyncRequest) -> SyncResponse:
    """
    同步知识库内容。

    从指定平台采集帖子，解析并写入知识库。
    """
    collector = get_collector()
    parser = get_parser()
    scorer = get_scorer()
    kb_manager = get_kb_manager()

    logger.info(f"[kb_api] 开始同步: platform={request.platform}, keyword={request.keyword}")

    try:
        # 1. 采集帖子
        collected_posts = await collector.search_posts(
            keyword=request.keyword,
            limit=request.limit,
        )

        # 如果有目的地要求，先过滤
        if request.destination:
            collected_posts = [
                p for p in collected_posts
                if request.destination in (p.get("destination") or "")
                or request.destination in (p.get("content", "") or p.get("desc", ""))
            ]

        # 2. 解析帖子
        parsed_posts = await parser.parse_batch(collected_posts)

        # 3. 评分
        scored_posts = scorer.score_batch(parsed_posts)

        # 4. 过滤并写入知识库
        ingested_count = 0
        skipped_count = 0
        failed_count = 0

        for post, score in scored_posts:
            try:
                post.quality_score = score
                if score >= 60.0:
                    success = await kb_manager.ingest_post(post)
                    if success:
                        ingested_count += 1
                    else:
                        skipped_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                logger.warning(f"[kb_api] 写入帖子失败 {post.post_id}: {e}")
                failed_count += 1

        logger.info(
            f"[kb_api] 同步完成: collected={len(collected_posts)}, "
            f"processed={len(parsed_posts)}, ingested={ingested_count}"
        )

        return SyncResponse(
            message="同步完成",
            collected=len(collected_posts),
            processed=len(parsed_posts),
            ingested=ingested_count,
            skipped=skipped_count,
            failed=failed_count,
        )

    except Exception as e:
        logger.error(f"[kb_api] 同步失败: {e}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/import")
async def import_posts(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    从上传文件导入帖子。
    
    支持多种格式：
    - JSON: 小红书帖子数据
    - 图片: JPG/PNG/GIF，使用多模态模型分析
    - PDF/Word/TXT: 提取文本内容
    """
    parser = get_parser()
    scorer = get_scorer()
    kb_manager = get_kb_manager()

    try:
        # 读取上传文件
        content = await file.read()

        # 临时保存上传文件
        temp_dir = Path(__file__).parent.parent.parent.parent / "data" / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / file.filename

        with open(temp_file, "wb") as f:
            f.write(content)

        # 使用多模态解析器解析文件
        parsed_posts = await parser.parse_file(temp_file)

        # 评分并写入知识库
        scored_posts = scorer.score_batch(parsed_posts)
        ingested_count = 0
        skipped_count = 0
        failed_count = 0

        for post, score in scored_posts:
            post.quality_score = score

            if score >= 60.0:
                try:
                    success = await kb_manager.ingest_post(post)
                    if success:
                        ingested_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    logger.warning(f"[kb_api] 写入帖子失败 {post.post_id}: {e}")
                    failed_count += 1
            else:
                skipped_count += 1

        # 清理临时文件
        temp_file.unlink()

        return {
            "message": "导入完成",
            "imported": len(parsed_posts),
            "ingested": ingested_count,
            "skipped": skipped_count,
            "failed": failed_count,
        }

    except Exception as e:
        logger.error(f"[kb_api] 导入失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """获取知识库统计信息"""
    collector = get_collector()
    kb_manager = get_kb_manager()

    try:
        collector_stats = await collector.get_stats()
        kb_stats = await kb_manager.get_stats()

        return StatsResponse(
            collector=collector_stats,
            knowledge_base=kb_stats,
        )
    except Exception as e:
        logger.error(f"[kb_api] 获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.post("/search", response_model=SearchResponse)
async def search_ugc(request: SearchRequest) -> SearchResponse:
    """搜索 UGC 内容"""
    kb_manager = get_kb_manager()

    try:
        results = await kb_manager.search_ugc(
            query=request.query,
            destination=request.destination,
            top_k=request.top_k,
        )

        return SearchResponse(
            results=results,
            total=len(results),
        )
    except Exception as e:
        logger.error(f"[kb_api] 搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.delete("/clear")
async def clear_knowledge_base(destination: str | None = None) -> dict[str, Any]:
    """清除知识库内容"""
    kb_manager = get_kb_manager()

    try:
        deleted_count = await kb_manager.clear_knowledge_base(destination)

        return {
            "message": "清除完成",
            "deleted": deleted_count,
        }
    except Exception as e:
        logger.error(f"[kb_api] 清除失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除失败: {str(e)}")
