"""
知识库同步脚本

用于命令行批量同步和导入 UGC 内容。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 添加项目路径
CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.knowledge_base.collectors.xiaohongshu_collector import XiaohongshuCollector
from app.knowledge_base.parsers.multimodal_parser import MultimodalParser
from app.knowledge_base.processors.quality_scorer import QualityScorer
from app.knowledge_base.storage.kb_manager import KnowledgeBaseManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def sync_platform(
    platform: str,
    keyword: str,
    destination: str | None = None,
    limit: int = 20,
    quality_threshold: float = 60.0,
) -> dict:
    """
    同步指定平台的内容。

    Args:
        platform: 平台名称
        keyword: 搜索关键词
        destination: 目的地过滤
        limit: 采集数量上限
        quality_threshold: 质量阈值

    Returns:
        同步统计
    """
    logger.info(f"开始同步: platform={platform}, keyword={keyword}")

    # 初始化组件
    collector = XiaohongshuCollector()
    parser = MultimodalParser()
    scorer = QualityScorer()
    kb_manager = KnowledgeBaseManager()

    stats = {
        "collected": 0,
        "parsed": 0,
        "ingested": 0,
        "skipped": 0,
        "failed": 0,
    }

    try:
        # 1. 采集帖子
        posts = await collector.search_posts(keyword=keyword, limit=limit)

        # 目的地过滤
        if destination:
            posts = [
                p for p in posts
                if destination in (p.get("destination") or "")
                or destination in (p.get("content", "") or p.get("desc", ""))
            ]

        stats["collected"] = len(posts)
        logger.info(f"采集到 {len(posts)} 条帖子")

        # 2. 解析帖子
        parsed_posts = await parser.parse_batch(posts)
        stats["parsed"] = len(parsed_posts)
        logger.info(f"解析了 {len(parsed_posts)} 条帖子")

        # 3. 评分
        scored_posts = scorer.score_batch(parsed_posts)

        # 4. 过滤并写入知识库
        for post, score in scored_posts:
            post.quality_score = score

            if score < quality_threshold:
                stats["skipped"] += 1
                logger.debug(f"帖子 {post.post_id} 质量分数 {score} 未达阈值，跳过")
                continue

            try:
                success = await kb_manager.ingest_post(post)
                if success:
                    stats["ingested"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning(f"写入帖子失败 {post.post_id}: {e}")
                stats["failed"] += 1

        logger.info(f"同步完成: {stats}")
        return stats

    except Exception as e:
        logger.error(f"同步过程出错: {e}")
        stats["error"] = str(e)
        return stats


async def import_from_file(
    filepath: str | Path,
    quality_threshold: float = 60.0,
) -> dict:
    """
    从文件导入帖子。
    支持多种格式：
    - JSON: 小红书帖子数据
    - 图片: JPG/PNG/GIF，使用多模态模型分析
    - PDF/Word/TXT: 提取文本内容

    Args:
        filepath: 文件路径
        quality_threshold: 质量阈值

    Returns:
        导入统计
    """
    logger.info(f"开始导入文件: {filepath}")

    parser = MultimodalParser()
    scorer = QualityScorer()
    kb_manager = KnowledgeBaseManager()

    stats = {
        "imported": 0,
        "parsed": 0,
        "ingested": 0,
        "skipped": 0,
        "failed": 0,
    }

    try:
        # 使用多模态解析器解析文件
        parsed_posts = await parser.parse_file(filepath)
        stats["imported"] = len(parsed_posts)
        logger.info(f"从文件解析出 {len(parsed_posts)} 条帖子")

        # 评分并写入知识库
        scored_posts = scorer.score_batch(parsed_posts)
        stats["parsed"] = len(scored_posts)

        for post, score in scored_posts:
            post.quality_score = score

            if score < quality_threshold:
                stats["skipped"] += 1
                logger.debug(f"帖子 {post.post_id} 质量分数 {score} 未达阈值，跳过")
                continue

            try:
                success = await kb_manager.ingest_post(post)
                if success:
                    stats["ingested"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning(f"写入帖子失败 {post.post_id}: {e}")
                stats["failed"] += 1

        logger.info(f"导入完成: {stats}")
        return stats

    except Exception as e:
        logger.error(f"导入过程出错: {e}")
        stats["error"] = str(e)
        return stats


async def main() -> int:
    """主函数"""
    parser = argparse.ArgumentParser(description="知识库同步工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # sync 子命令
    sync_parser = subparsers.add_parser("sync", help="同步平台内容")
    sync_parser.add_argument("--platform", default="xiaohongshu", help="平台名称")
    sync_parser.add_argument("--keyword", default="旅行", help="搜索关键词")
    sync_parser.add_argument("--destination", default=None, help="目的地过滤")
    sync_parser.add_argument("--limit", type=int, default=20, help="采集数量上限")
    sync_parser.add_argument("--threshold", type=float, default=60.0, help="质量阈值")

    # import 子命令
    import_parser = subparsers.add_parser("import", help="从文件导入")
    import_parser.add_argument("filepath", help="JSON 文件路径")
    import_parser.add_argument("--threshold", type=float, default=60.0, help="质量阈值")

    # stats 子命令
    stats_parser = subparsers.add_parser("stats", help="查看统计信息")

    # clear 子命令
    clear_parser = subparsers.add_parser("clear", help="清除知识库")
    clear_parser.add_argument("--destination", default=None, help="指定目的地")

    args = parser.parse_args()

    if args.command == "sync":
        stats = await sync_platform(
            platform=args.platform,
            keyword=args.keyword,
            destination=args.destination,
            limit=args.limit,
            quality_threshold=args.threshold,
        )
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return 0

    elif args.command == "import":
        stats = await import_from_file(
            filepath=args.filepath,
            quality_threshold=args.threshold,
        )
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return 0

    elif args.command == "stats":
        collector = XiaohongshuCollector()
        kb_manager = KnowledgeBaseManager()

        collector_stats = await collector.get_stats()
        kb_stats = await kb_manager.get_stats()

        print(json.dumps({
            "collector": collector_stats,
            "knowledge_base": kb_stats,
        }, indent=2, ensure_ascii=False))
        return 0

    elif args.command == "clear":
        kb_manager = KnowledgeBaseManager()
        deleted = await kb_manager.clear_knowledge_base(args.destination)
        print(json.dumps({"deleted": deleted}, indent=2))
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
