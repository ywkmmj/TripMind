"""
采集器基类

定义数据采集的统一接口和通用功能。
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """
    社交平台数据采集器基类。

    所有平台采集器需继承此类并实现平台特定的方法。
    """

    PLATFORM_NAME: str = "base"
    DATA_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "user_generated"

    def __init__(self, storage_dir: Path | None = None):
        """
        初始化采集器。

        Args:
            storage_dir: 数据存储目录，默认为 data/user_generated/{platform}/
        """
        self.storage_dir = storage_dir or (self.DATA_DIR / self.PLATFORM_NAME)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def search_posts(self, keyword: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        搜索相关帖子。

        Args:
            keyword: 搜索关键词
            limit: 返回数量上限

        Returns:
            帖子列表，每条帖子包含基本信息
        """

    @abstractmethod
    async def get_post_detail(self, post_id: str) -> dict[str, Any] | None:
        """
        获取帖子详情。

        Args:
            post_id: 帖子唯一标识

        Returns:
            帖子详情，包含完整正文和图片列表
        """

    async def save_post(self, post_data: dict[str, Any]) -> str:
        """
        保存原始帖子数据到本地。

        Args:
            post_data: 帖子数据

        Returns:
            保存的文件路径
        """
        post_id = post_data.get("post_id", post_data.get("id", "unknown"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{post_id}_{timestamp}.json"
        filepath = self.storage_dir / filename

        # 确保目录存在
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(post_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[{self.PLATFORM_NAME}] 保存帖子 {post_id} 到 {filepath}")
        return str(filepath)

    async def load_saved_posts(self, destination: str | None = None) -> list[dict[str, Any]]:
        """
        加载已保存的帖子数据。

        Args:
            destination: 可选，按目的地过滤

        Returns:
            帖子列表
        """
        posts = []
        pattern = "*.json" if not destination else f"*{destination}*.json"

        for filepath in self.storage_dir.rglob(pattern):
            try:
                with open(filepath, encoding="utf-8") as f:
                    post = json.load(f)
                    posts.append(post)
            except Exception as e:
                logger.warning(f"加载帖子失败 {filepath}: {e}")

        return posts

    def extract_destination_from_content(self, content: str) -> str | None:
        """
        从内容中提取目的地信息。

        使用简单规则匹配已知目的地名称。

        Args:
            content: 帖子文本内容

        Returns:
            匹配到的目的地名称，未匹配返回 None
        """
        known_destinations = [
            "西安", "大理", "丽江", "杭州", "成都", "重庆", "厦门", "三亚",
            "北京", "上海", "广州", "深圳", "苏州", "南京", "青岛", "长沙",
            "武汉", "西安", "天津", "郑州", "济南", "石家庄", "太原", "呼和浩特",
            "哈尔滨", "长春", "沈阳", "大连", "昆明", "贵阳", "拉萨", "西宁",
            "兰州", "乌鲁木齐", "银川", "海口", "北海", "桂林", "张家界", "凤凰",
        ]

        for dest in known_destinations:
            if dest in content:
                return dest
        return None

    def parse_hashtags(self, content: str) -> list[str]:
        """
        从正文中提取话题标签。

        Args:
            content: 帖子正文

        Returns:
            话题标签列表
        """
        import re
        hashtags = re.findall(r"#(\w+)", content)
        return list(set(hashtags))

    async def collect_and_save(
        self,
        keyword: str,
        destination: str | None = None,
        limit: int = 20,
    ) -> list[str]:
        """
        采集并保存帖子。

        Args:
            keyword: 搜索关键词
            destination: 目的地（用于过滤）
            limit: 采集数量上限

        Returns:
            保存的文件路径列表
        """
        logger.info(f"[{self.PLATFORM_NAME}] 开始采集: keyword={keyword}, limit={limit}")

        posts = await self.search_posts(keyword, limit=limit)
        saved_paths = []

        for post in posts:
            # 提取目的地
            content = post.get("content", "") or post.get("desc", "") or ""
            post_dest = self.extract_destination_from_content(content) if content else None

            # 如果指定了目的地但未匹配，跳过
            if destination and post_dest != destination:
                continue

            post["platform"] = self.PLATFORM_NAME
            post["collected_at"] = datetime.now().isoformat()
            post["destination"] = post_dest

            saved_path = await self.save_post(post)
            saved_paths.append(saved_path)

        logger.info(f"[{self.PLATFORM_NAME}] 采集完成: 采集 {len(saved_paths)} 条帖子")
        return saved_paths
