"""
知识库管理器

负责 UGC 内容的存储、检索和管理。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import (
    BACKEND_DIR,
    CHROMA_COLLECTION_NAME,
    CHROMA_DB_DIR,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
)
from app.knowledge_base.parsers.multimodal_parser import StructuredPost
from app.knowledge_base.processors.quality_scorer import QualityScorer

logger = logging.getLogger(__name__)

# 知识库配置
KB_DATA_DIR = BACKEND_DIR / "data" / "user_generated"
KB_MARKDOWN_DIR = KB_DATA_DIR / "markdown"
UGC_QUALITY_THRESHOLD = float(os.getenv("UGC_QUALITY_THRESHOLD", "60"))
UGC_MAX_POSTS_PER_DEST = int(os.getenv("UGC_MAX_POSTS_PER_DESTINATION", "100"))


class KnowledgeBaseManager:
    """
    知识库管理器。

    负责：
    1. UGC 内容的存储和管理
    2. Markdown 格式转换（兼容现有知识库格式）
    3. 向量库写入
    4. 检索接口
    """

    def __init__(self):
        """初始化知识库管理器"""
        self.scorer = QualityScorer()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """确保必要目录存在"""
        KB_DATA_DIR.mkdir(parents=True, exist_ok=True)
        KB_MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    async def ingest_post(self, post: StructuredPost) -> bool:
        """
        将结构化帖子内容写入知识库。

        Args:
            post: 结构化帖子数据

        Returns:
            是否成功
        """
        try:
            # 1. 计算质量分数
            quality_score = self.scorer.calculate_score(post)
            post.quality_score = quality_score

            if quality_score < UGC_QUALITY_THRESHOLD:
                logger.info(f"[kb_manager] 帖子 {post.post_id} 质量分数 {quality_score} 未达阈值，跳过")
                return False

            # 2. 转换为 Markdown 格式
            markdown_content = self._post_to_markdown(post)

            # 3. 保存 Markdown 文件
            markdown_path = self._save_markdown(post, markdown_content)

            # 4. 保存元数据 JSON
            metadata_path = self._save_metadata(post)

            logger.info(f"[kb_manager] 帖子 {post.post_id} 已写入知识库: {markdown_path}")
            return True

        except Exception as e:
            logger.error(f"[kb_manager] 帖子写入失败 {post.post_id}: {e}")
            return False

    async def ingest_posts(self, posts: list[StructuredPost]) -> dict[str, int]:
        """
        批量写入帖子到知识库。

        Args:
            posts: 结构化帖子列表

        Returns:
            写入统计 {"total": N, "success": M, "skipped": K, "failed": F}
        """
        stats = {"total": len(posts), "success": 0, "skipped": 0, "failed": 0}

        for post in posts:
            try:
                success = await self.ingest_post(post)
                if success:
                    stats["success"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning(f"[kb_manager] 帖子处理失败 {post.post_id}: {e}")
                stats["failed"] += 1

        logger.info(f"[kb_manager] 批量写入完成: {stats}")
        return stats

    def _post_to_markdown(self, post: StructuredPost) -> str:
        """
        将结构化帖子转换为 Markdown 格式。

        格式与官方攻略兼容，便于统一检索。

        Args:
            post: 结构化帖子数据

        Returns:
            Markdown 格式字符串
        """
        lines = [
            f"# [用户游记] {post.title}",
            "",
            "## 基础信息",
            f"- **作者**: {post.author}",
            f"- **来源**: {post.platform}",
            f"- **发布时间**: {post.publish_time.strftime('%Y-%m-%d') if post.publish_time else '未知'}",
            f"- **点赞数**: {post.likes}",
            f"- **评论数**: {post.comments}",
            f"- **质量评分**: {post.quality_score:.1f}",
            f"- **目的地**: {post.destination or '未指定'}",
            "",
            "## 标签",
        ]

        # 添加标签
        if post.tags:
            lines.append(", ".join(f"`{tag}`" for tag in post.tags))
        else:
            lines.append("无")
        lines.append("")

        # 核心体验摘要
        lines.append("## 核心体验摘要")
        lines.append(post.summary if post.summary else post.content[:300])
        lines.append("")

        # 景点 & 活动推荐
        if post.key_attractions:
            lines.append("## 景点 & 活动推荐")
            for attr in post.key_attractions:
                name = attr.get("name", "")
                highlight = attr.get("highlight", "")
                tips = attr.get("tips", "")
                lines.append(f"### {name}")
                if highlight:
                    lines.append(f"- 亮点：{highlight}")
                if tips:
                    lines.append(f"- 建议：{tips}")
                lines.append("")
        else:
            lines.append("## 景点 & 活动推荐")
            lines.append("未提取到具体景点信息。")
            lines.append("")

        # 美食推荐
        if post.food_recommendations:
            lines.append("## 美食推荐")
            for food in post.food_recommendations:
                name = food.get("name", "")
                dish = food.get("dish", "")
                price = food.get("price", "")
                lines.append(f"### {name}")
                if dish:
                    lines.append(f"- 推荐菜：{dish}")
                if price:
                    lines.append(f"- 预算：{price}")
                lines.append("")
        else:
            lines.append("## 美食推荐")
            lines.append("未提取到美食信息。")
            lines.append("")

        # 实用 Tips
        lines.append("## 实用 Tips")
        if post.experience_tips:
            for tip in post.experience_tips:
                lines.append(f"- {tip}")
        else:
            lines.append("暂无实用 Tips。")
        lines.append("")

        # 时间信息
        if post.timing_info:
            lines.append("## 时间信息")
            for key, value in post.timing_info.items():
                if value:
                    lines.append(f"- {key}：{value}")
                else:
                    lines.append(f"- {key}")
            lines.append("")

        # 预算信息
        if post.budget_estimate:
            lines.append("## 预算参考")
            budget = post.budget_estimate
            if "range" in budget:
                lines.append(f"- 总预算范围：{budget['range']}")
            if "breakdown" in budget:
                for category, amount in budget["breakdown"].items():
                    lines.append(f"- {category}：{amount}")
            lines.append("")

        return "\n".join(lines)

    def _save_markdown(self, post: StructuredPost, content: str) -> Path:
        """
        保存 Markdown 文件。

        Args:
            post: 结构化帖子数据
            content: Markdown 内容

        Returns:
            保存的文件路径
        """
        # 按目的地分组存储
        dest = post.destination or "unknown"
        dest_dir = KB_MARKDOWN_DIR / dest
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        timestamp = post.publish_time.strftime("%Y%m%d") if post.publish_time else "unknown"
        filename = f"{post.post_id}_{timestamp}.md"
        filepath = dest_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return filepath

    def _save_metadata(self, post: StructuredPost) -> Path:
        """
        保存帖子元数据。

        Args:
            post: 结构化帖子数据

        Returns:
            元数据文件路径
        """
        metadata_dir = KB_DATA_DIR / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{post.post_id}.json"
        filepath = metadata_dir / filename

        metadata = {
            "post_id": post.post_id,
            "platform": post.platform,
            "author": post.author,
            "title": post.title,
            "destination": post.destination,
            "publish_time": post.publish_time.isoformat() if post.publish_time else None,
            "likes": post.likes,
            "comments": post.comments,
            "quality_score": post.quality_score,
            "tags": post.tags,
            "ingested_at": datetime.now().isoformat(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return filepath

    def load_ugc_chunks(self, destination: str | None = None) -> list[dict[str, str]]:
        """
        加载 UGC 内容片段。

        兼容现有 load_guide_chunks 的返回格式。

        Args:
            destination: 可选，按目的地过滤

        Returns:
            片段列表
        """
        chunks = []
        search_dir = KB_MARKDOWN_DIR if not destination else KB_MARKDOWN_DIR / destination
        pattern = "*.md"

        for filepath in search_dir.rglob(pattern):
            try:
                content = filepath.read_text(encoding="utf-8")
                chunks.append(self._split_markdown_chunk(filepath.name, content, str(filepath)))
            except Exception as e:
                logger.warning(f"[kb_manager] 加载 UGC 文件失败 {filepath}: {e}")

        return chunks

    def _split_markdown_chunk(self, filename: str, content: str, source: str) -> dict[str, str]:
        """
        切分 Markdown 内容。

        复用 vector_db.py 的切分逻辑。

        Args:
            filename: 文件名
            content: 文件内容
            source: 来源路径

        Returns:
            片段字典
        """
        # 简单的按标题切分
        lines = content.splitlines()
        title = "用户游记"
        text_lines = []

        for line in lines:
            if line.startswith("## "):
                if text_lines:
                    break
                title = line.replace("## ", "").strip()
            elif line.startswith("# ") and not text_lines:
                title = line.replace("# ", "").strip()
            else:
                text_lines.append(line)

        return {
            "title": title,
            "text": "\n".join(text_lines).strip(),
            "source": source,
        }

    async def search_ugc(
        self,
        query: str,
        destination: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        搜索 UGC 内容。

        Args:
            query: 搜索查询
            destination: 目的地
            top_k: 返回数量

        Returns:
            匹配的 UGC 内容列表
        """
        chunks = self.load_ugc_chunks(destination)

        if not chunks:
            return []

        # 简单的关键词匹配搜索
        query_keywords = self._extract_keywords(query)
        scored_chunks = []

        for chunk in chunks:
            score = 0
            title = chunk.get("title", "").lower()
            text = chunk.get("text", "").lower()

            for keyword in query_keywords:
                if keyword.lower() in title:
                    score += 3
                if keyword.lower() in text:
                    score += 1

            if score > 0:
                chunk_copy = dict(chunk)
                chunk_copy["score"] = score
                chunk_copy["is_ugc"] = True
                scored_chunks.append(chunk_copy)

        # 按分数排序
        scored_chunks.sort(key=lambda x: x["score"], reverse=True)

        return scored_chunks[:top_k]

    def _extract_keywords(self, query: str) -> list[str]:
        """提取关键词"""
        import re
        keywords = re.split(r"[\s,，。；;、]+", query)
        return [k.strip() for k in keywords if k.strip()]

    async def get_stats(self) -> dict[str, Any]:
        """
        获取知识库统计信息。

        Returns:
            统计信息
        """
        stats = {
            "total_posts": 0,
            "by_destination": {},
            "by_platform": {},
            "average_quality": 0.0,
        }

        metadata_dir = KB_DATA_DIR / "metadata"
        if not metadata_dir.exists():
            return stats

        quality_scores = []

        for filepath in metadata_dir.glob("*.json"):
            try:
                with open(filepath, encoding="utf-8") as f:
                    metadata = json.load(f)

                stats["total_posts"] += 1

                # 按目的地统计
                dest = metadata.get("destination", "未知")
                stats["by_destination"][dest] = stats["by_destination"].get(dest, 0) + 1

                # 按平台统计
                platform = metadata.get("platform", "未知")
                stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1

                # 收集质量分数
                score = metadata.get("quality_score", 0)
                if score > 0:
                    quality_scores.append(score)

            except Exception as e:
                logger.warning(f"[kb_manager] 加载元数据失败 {filepath}: {e}")

        if quality_scores:
            stats["average_quality"] = round(sum(quality_scores) / len(quality_scores), 2)

        return stats

    async def clear_knowledge_base(self, destination: str | None = None) -> int:
        """
        清除知识库内容。

        Args:
            destination: 可选，只清除指定目的地的内容

        Returns:
            删除的文件数量
        """
        deleted_count = 0

        if destination:
            # 清除指定目的地
            markdown_dir = KB_MARKDOWN_DIR / destination
            if markdown_dir.exists():
                for filepath in markdown_dir.glob("*.md"):
                    filepath.unlink()
                    deleted_count += 1
        else:
            # 清除全部
            for filepath in KB_MARKDOWN_DIR.rglob("*.md"):
                filepath.unlink()
                deleted_count += 1

            metadata_dir = KB_DATA_DIR / "metadata"
            if metadata_dir.exists():
                for filepath in metadata_dir.glob("*.json"):
                    filepath.unlink()
                    deleted_count += 1

        logger.info(f"[kb_manager] 清除知识库: 删除 {deleted_count} 个文件")
        return deleted_count


def get_kb_manager() -> KnowledgeBaseManager:
    """获取知识库管理器实例"""
    return KnowledgeBaseManager()
