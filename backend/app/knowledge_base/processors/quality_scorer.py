"""
质量评分器

对用户生成内容进行多维度质量评估。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from app.knowledge_base.parsers.multimodal_parser import StructuredPost

logger = logging.getLogger(__name__)


class QualityScorer:
    """
    UGC 内容质量评分器。

    综合多个维度评估内容质量：
    1. 互动数据（点赞、评论）
    2. 内容质量（长度、信息量、结构化程度）
    3. 时效性（发布时间的时效性）
    4. 实用度（Tips、预算、景点信息）
    """

    # 权重配置
    WEIGHTS = {
        "engagement": 0.25,      # 互动数据权重
        "content_quality": 0.30, # 内容质量权重
        "timeliness": 0.20,      # 时效性权重
        "usefulness": 0.25,      # 实用度权重
    }

    # 内容质量阈值
    MIN_CONTENT_LENGTH = 100      # 最小内容长度
    MAX_CONTENT_LENGTH = 10000   # 最大内容长度
    IDEAL_CONTENT_LENGTH = 500   # 理想内容长度

    def __init__(self):
        """初始化评分器"""
        self.weights = self.WEIGHTS.copy()

    def calculate_score(self, post: StructuredPost) -> float:
        """
        计算综合质量分数。

        Args:
            post: 结构化帖子数据

        Returns:
            质量分数 (0-100)
        """
        scores = {
            "engagement": self._score_engagement(post),
            "content_quality": self._score_content(post),
            "timeliness": self._score_timeliness(post),
            "usefulness": self._score_usefulness(post),
        }

        # 计算加权平均
        total_score = sum(
            scores[key] * self.weights[key]
            for key in scores
        )

        # 确保分数在 0-100 范围内
        final_score = max(0.0, min(100.0, total_score))

        logger.debug(
            f"[quality_scorer] post_id={post.post_id}, "
            f"scores={scores}, final={final_score:.2f}"
        )

        return round(final_score, 2)

    def _score_engagement(self, post: StructuredPost) -> float:
        """
        评估互动数据分数。

        基于点赞数和评论数计算。

        Args:
            post: 结构化帖子数据

        Returns:
            互动分数 (0-100)
        """
        likes = post.likes or 0
        comments = post.comments or 0

        # 使用对数缩放，避免极端值影响过大
        # 点赞分：0-5000 点赞对应 0-60 分
        likes_score = min(60, (likes ** 0.5) * 3)

        # 评论分：0-500 评论对应 0-40 分
        comments_score = min(40, (comments ** 0.5) * 2)

        return likes_score + comments_score

    def _score_content(self, post: StructuredPost) -> float:
        """
        评估内容质量分数。

        基于内容长度、信息密度、结构化程度评估。

        Args:
            post: 结构化帖子数据

        Returns:
            内容质量分数 (0-100)
        """
        content = post.content or ""
        content_length = len(content)

        # 长度分数
        if content_length < self.MIN_CONTENT_LENGTH:
            length_score = (content_length / self.MIN_CONTENT_LENGTH) * 40
        elif content_length > self.MAX_CONTENT_LENGTH:
            length_score = 40 - ((content_length - self.MAX_CONTENT_LENGTH) / 1000) * 10
            length_score = max(0, length_score)
        else:
            # 理想长度附近给高分
            deviation = abs(content_length - self.IDEAL_CONTENT_LENGTH)
            length_score = 40 - (deviation / 100)

        # 结构化分数
        structure_score = 0

        if post.summary:
            structure_score += 10

        if len(post.key_attractions) > 0:
            structure_score += 10

        if len(post.food_recommendations) > 0:
            structure_score += 10

        if len(post.experience_tips) > 0:
            structure_score += 10

        if post.timing_info:
            structure_score += 5

        if post.budget_estimate:
            structure_score += 5

        # 图片分数
        image_score = min(10, len(post.images) * 2)

        return min(100, length_score + structure_score + image_score)

    def _score_timeliness(self, post: StructuredPost) -> float:
        """
        评估时效性分数。

        基于发布时间距离现在的天数。

        Args:
            post: 结构化帖子数据

        Returns:
            时效性分数 (0-100)
        """
        if not post.publish_time:
            return 50  # 无时间信息给中等分

        now = datetime.now()
        days_old = (now - post.publish_time).days

        if days_old < 0:
            # 未来时间，视为无效
            return 0

        # 7 天内：90-100 分
        if days_old <= 7:
            return 100 - days_old * 1.5

        # 7-30 天：70-90 分
        if days_old <= 30:
            return 90 - (days_old - 7) * 0.7

        # 30-90 天：50-70 分
        if days_old <= 90:
            return 70 - (days_old - 30) * 0.5

        # 90-365 天：30-50 分
        if days_old <= 365:
            return 50 - (days_old - 90) * 0.07

        # 超过 1 年：逐渐衰减到 20 分
        return max(20, 30 - (days_old - 365) * 0.02)

    def _score_usefulness(self, post: StructuredPost) -> float:
        """
        评估实用度分数。

        基于是否有实用 Tips、预算信息、景点推荐等。

        Args:
            post: 结构化帖子数据

        Returns:
            实用度分数 (0-100)
        """
        score = 0

        # 景点推荐 (0-25 分)
        attractions = post.key_attractions or []
        if attractions:
            score += min(25, len(attractions) * 8)

        # 美食推荐 (0-20 分)
        foods = post.food_recommendations or []
        if foods:
            score += min(20, len(foods) * 7)

        # 实用 Tips (0-25 分)
        tips = post.experience_tips or []
        if tips:
            score += min(25, len(tips) * 8)

        # 时间/季节信息 (0-15 分)
        if post.timing_info:
            timing_keys = post.timing_info.keys()
            if any(k for k in timing_keys if k):
                score += 15

        # 预算信息 (0-15 分)
        if post.budget_estimate:
            score += 15

        return min(100, score)

    def is_quality_content(self, post: StructuredPost, threshold: float = 60.0) -> bool:
        """
        判断内容是否达到质量标准。

        Args:
            post: 结构化帖子数据
            threshold: 质量阈值，默认 60 分

        Returns:
            是否达标
        """
        score = self.calculate_score(post)
        return score >= threshold

    def score_batch(self, posts: list[StructuredPost]) -> list[tuple[StructuredPost, float]]:
        """
        批量评分。

        Args:
            posts: 帖子列表

        Returns:
            (帖子, 分数) 元组列表
        """
        results = []

        for post in posts:
            score = self.calculate_score(post)
            results.append((post, score))

        # 按分数降序排列
        results.sort(key=lambda x: x[1], reverse=True)

        return results

    def filter_by_threshold(
        self,
        posts: list[StructuredPost],
        threshold: float = 60.0,
    ) -> list[StructuredPost]:
        """
        按阈值过滤内容。

        Args:
            posts: 帖子列表
            threshold: 质量阈值

        Returns:
            达标的帖子列表
        """
        filtered = []

        for post in posts:
            if self.is_quality_content(post, threshold):
                filtered.append(post)

        logger.info(
            f"[quality_scorer] 过滤完成: "
            f"原始 {len(posts)} 条, 达标 {len(filtered)} 条"
        )

        return filtered


def get_default_scorer() -> QualityScorer:
    """获取默认评分器实例"""
    return QualityScorer()
