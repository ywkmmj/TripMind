"""
小红书采集器

采集小红书平台的旅行帖子内容。
支持三种模式：
1. 本地文件导入：上传本地 JSON 文件导入帖子
2. 爬虫模式：使用 Playwright 爬取公开内容（仅供研究学习）
3. API 模式（预留）：通过官方 API 获取数据
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class XiaohongshuCollector:
    """
    小红书数据采集器。

    支持本地导入和爬虫两种模式：
    1. 本地文件导入：适合个人用户手动收集数据
    2. 爬虫模式：使用 Playwright 爬取公开内容

    ⚠️ 注意：爬虫仅供研究学习使用，请遵守平台规则和法律法规。
    实际生产环境建议通过官方 API 或数据合作方式获取。
    """

    PLATFORM_NAME = "xiaohongshu"
    DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "user_generated" / "xiaohongshu"

    def __init__(self, storage_dir: Path | None = None, use_crawler: bool = False):
        """
        初始化小红书采集器。

        Args:
            storage_dir: 数据存储目录
            use_crawler: 是否启用爬虫模式
        """
        self.storage_dir = storage_dir or self.DATA_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.use_crawler = use_crawler

        # API 配置（预留）
        self.api_key = os.getenv("XIAOHONGSHU_API_KEY", "")
        self.api_base_url = os.getenv("XIAOHONGSHU_API_URL", "https://api.xiaohongshu.com")

        # 爬虫配置
        self.crawler_enabled = use_crawler or os.getenv("ENABLE_XHS_CRAWLER", "false").lower() == "true"
        self._browser = None

    async def search_posts(self, keyword: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        搜索小红书帖子。

        如果启用爬虫模式，会尝试爬取公开内容；
        否则返回本地已导入的数据。

        Args:
            keyword: 搜索关键词
            limit: 返回数量上限

        Returns:
            帖子列表
        """
        logger.info(f"[xiaohongshu] 搜索帖子: keyword={keyword}, limit={limit}, crawler={self.crawler_enabled}")

        posts = []

        # 如果启用爬虫，先尝试爬取
        if self.crawler_enabled:
            try:
                crawled_posts = await self._crawl_search(keyword, limit)
                posts.extend(crawled_posts)
                logger.info(f"[xiaohongshu] 爬虫获取 {len(crawled_posts)} 条帖子")
            except Exception as e:
                logger.warning(f"[xiaohongshu] 爬虫失败，使用本地数据: {e}")

        # 补充本地数据
        if len(posts) < limit:
            local_posts = await self.load_saved_posts()
            keyword_lower = keyword.lower()
            for post in local_posts:
                title = post.get("title", "").lower()
                content = post.get("content", "").lower()
                tags = " ".join(post.get("tags", [])).lower()

                if keyword_lower in title or keyword_lower in content or keyword_lower in tags:
                    # 去重
                    if post.get("post_id") not in [p.get("post_id") for p in posts]:
                        posts.append(post)
                        if len(posts) >= limit:
                            break

        return posts[:limit]

    async def get_post_detail(self, post_id: str) -> dict[str, Any] | None:
        """
        获取帖子详情。

        Args:
            post_id: 帖子 ID

        Returns:
            帖子详情，未找到返回 None
        """
        # 先尝试从本地加载
        for filepath in self.storage_dir.rglob("*.json"):
            try:
                with open(filepath, encoding="utf-8") as f:
                    post = json.load(f)
                    if post.get("post_id") == post_id or post.get("id") == post_id:
                        # 如果启用爬虫且内容不完整，尝试补充
                        if self.crawler_enabled and not post.get("content"):
                            detail = await self._crawl_post_detail(post_id)
                            if detail:
                                return detail
                        return post
            except Exception:
                continue

        # 尝试爬虫获取
        if self.crawler_enabled:
            return await self._crawl_post_detail(post_id)

        logger.warning(f"[xiaohongshu] 帖子 {post_id} 未找到")
        return None

    async def save_post(self, post_data: dict[str, Any]) -> str:
        """
        保存帖子数据到本地。

        Args:
            post_data: 帖子数据

        Returns:
            保存的文件路径
        """
        post_id = post_data.get("post_id") or post_data.get("id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{post_id}_{timestamp}.json"
        filepath = self.storage_dir / filename

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(post_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[xiaohongshu] 保存帖子 {post_id} 到 {filepath}")
        return str(filepath)

    async def import_from_file(self, filepath: str | Path) -> list[str]:
        """
        从本地文件导入帖子数据。

        支持两种格式：
        1. 单个帖子 JSON 文件
        2. 帖子列表 JSON 文件

        Args:
            filepath: 文件路径

        Returns:
            导入的帖子数量
        """
        filepath = Path(filepath)
        saved_paths = []

        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                posts = data
            elif isinstance(data, dict):
                posts = [data]
            else:
                logger.error(f"[xiaohongshu] 不支持的数据格式: {type(data)}")
                return []

            for post in posts:
                post["platform"] = self.PLATFORM_NAME
                post["imported_at"] = datetime.now().isoformat()

                # 生成唯一 ID
                if "post_id" not in post:
                    post["post_id"] = f"imported_{len(saved_paths) + 1}_{datetime.now().timestamp()}"

                saved_path = await self.save_post(post)
                saved_paths.append(saved_path)

            logger.info(f"[xiaohongshu] 从 {filepath} 导入 {len(saved_paths)} 条帖子")
            return saved_paths

        except Exception as e:
            logger.error(f"[xiaohongshu] 导入失败 {filepath}: {e}")
            return []

    async def load_saved_posts(self, destination: str | None = None) -> list[dict[str, Any]]:
        """
        加载已保存的帖子数据。

        Args:
            destination: 可选，按目的地过滤

        Returns:
            帖子列表
        """
        posts = []
        pattern = "*.json"

        for filepath in self.storage_dir.rglob(pattern):
            try:
                with open(filepath, encoding="utf-8") as f:
                    post = json.load(f)

                if destination:
                    post_dest = post.get("destination", "")
                    if destination not in post_dest and destination not in post.get("content", ""):
                        continue

                posts.append(post)
            except Exception as e:
                logger.warning(f"[xiaohongshu] 加载帖子失败 {filepath}: {e}")

        return posts

    def extract_destination_from_content(self, content: str) -> str | None:
        """从内容中提取目的地信息"""
        known_destinations = [
            "西安", "大理", "丽江", "杭州", "成都", "重庆", "厦门", "三亚",
            "北京", "上海", "广州", "深圳", "苏州", "南京", "青岛", "长沙",
            "武汉", "天津", "郑州", "济南", "石家庄", "太原", "呼和浩特",
            "哈尔滨", "长春", "沈阳", "大连", "昆明", "贵州", "拉萨", "西宁",
            "兰州", "乌鲁木齐", "银川", "海口", "北海", "桂林", "张家界", "凤凰",
        ]

        for dest in known_destinations:
            if dest in content:
                return dest
        return None

    def parse_hashtags(self, content: str) -> list[str]:
        """从正文中提取话题标签"""
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
            destination: 目的地
            limit: 采集数量上限

        Returns:
            保存的文件路径列表
        """
        posts = await self.search_posts(keyword, limit=limit)
        saved_paths = []

        for post in posts:
            content = post.get("content", "") or post.get("desc", "") or ""
            post_dest = self.extract_destination_from_content(content) if content else None

            if destination and post_dest != destination:
                continue

            post["platform"] = self.PLATFORM_NAME
            post["collected_at"] = datetime.now().isoformat()
            post["destination"] = post_dest

            saved_path = await self.save_post(post)
            saved_paths.append(saved_path)

        logger.info(f"[xiaohongshu] 采集完成: 保存 {len(saved_paths)} 条帖子")
        return saved_paths

    async def get_stats(self) -> dict[str, Any]:
        """获取采集器统计信息"""
        posts = await self.load_saved_posts()
        destinations = {}

        for post in posts:
            dest = post.get("destination", "未知")
            destinations[dest] = destinations.get(dest, 0) + 1

        return {
            "platform": self.PLATFORM_NAME,
            "total_posts": len(posts),
            "destinations": destinations,
            "storage_dir": str(self.storage_dir),
            "crawler_enabled": self.crawler_enabled,
        }

    # ==================== 爬虫相关方法 ====================

    async def _crawl_search(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        爬取搜索结果。

        ⚠️ 仅供研究学习使用，请遵守平台规则。

        Args:
            keyword: 搜索关键词
            limit: 返回数量上限

        Returns:
            帖子列表
        """
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # 设置用户代理
                await page.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                # 访问搜索页面
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}"
                await page.goto(search_url, timeout=30000)

                # 等待页面加载
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2 + random.random())

                # 滚动加载更多内容
                posts = []
                scroll_count = 0
                max_scroll = 3

                while len(posts) < limit and scroll_count < max_scroll:
                    # 提取帖子数据
                    current_posts = await self._extract_posts_from_page(page)
                    for post in current_posts:
                        if post.get("post_id") and post.get("post_id") not in [p.get("post_id") for p in posts]:
                            posts.append(post)
                            if len(posts) >= limit:
                                break

                    if len(posts) >= limit:
                        break

                    # 滚动页面
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2 + random.random())
                    scroll_count += 1

                await browser.close()
                return posts[:limit]

        except ImportError:
            logger.warning("[xiaohongshu] 未安装 playwright，请安装: pip install playwright")
            return []
        except Exception as e:
            logger.error(f"[xiaohongshu] 爬虫搜索失败: {e}")
            return []

    async def _crawl_post_detail(self, post_id: str) -> dict[str, Any] | None:
        """
        爬取帖子详情。

        ⚠️ 仅供研究学习使用，请遵守平台规则。

        Args:
            post_id: 帖子 ID

        Returns:
            帖子详情
        """
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # 设置用户代理
                await page.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

                # 访问帖子页面
                post_url = f"https://www.xiaohongshu.com/discovery/item/{post_id}"
                await page.goto(post_url, timeout=30000)

                # 等待页面加载
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2 + random.random())

                # 提取帖子详情
                post_data = await self._extract_post_detail(page)
                post_data["post_id"] = post_id

                await browser.close()
                return post_data

        except Exception as e:
            logger.error(f"[xiaohongshu] 爬取帖子详情失败 {post_id}: {e}")
            return None

    async def _extract_posts_from_page(self, page) -> list[dict[str, Any]]:
        """从搜索页面提取帖子列表"""
        posts = []

        try:
            # 使用 JavaScript 提取数据
            items = await page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('div[class*="note-item"]');
                    const results = [];
                    cards.forEach(card => {
                        const title = card.querySelector('h3')?.textContent || '';
                        const desc = card.querySelector('p')?.textContent || '';
                        const img = card.querySelector('img')?.src || '';
                        const likes = card.querySelector('[class*="like"]')?.textContent || '0';
                        const comments = card.querySelector('[class*="comment"]')?.textContent || '0';
                        const href = card.querySelector('a')?.href || '';
                        
                        // 从 URL 提取 post_id
                        const match = href.match(/item\\/(\\w+)/);
                        const postId = match ? match[1] : '';
                        
                        if (title || desc) {
                            results.push({
                                post_id: postId,
                                title: title.trim(),
                                desc: desc.trim(),
                                images: img ? [img] : [],
                                likes: parseInt(likes) || 0,
                                comments: parseInt(comments) || 0,
                                url: href
                            });
                        }
                    });
                    return results;
                }
            """)

            posts.extend(items)
        except Exception as e:
            logger.warning(f"[xiaohongshu] 提取帖子列表失败: {e}")

        return posts

    async def _extract_post_detail(self, page) -> dict[str, Any]:
        """从帖子详情页提取数据"""
        try:
            data = await page.evaluate("""
                () => {
                    const title = document.querySelector('h1')?.textContent || '';
                    const content = document.querySelector('article')?.textContent || '';
                    const author = document.querySelector('[class*="username"]')?.textContent || '';
                    const likes = document.querySelector('[class*="like-count"]')?.textContent || '0';
                    const comments = document.querySelector('[class*="comment-count"]')?.textContent || '0';
                    
                    // 提取图片
                    const images = [];
                    document.querySelectorAll('img[src*="xiaohongshu"]').forEach(img => {
                        if (img.src && !img.src.includes('avatar')) {
                            images.push(img.src);
                        }
                    });
                    
                    // 提取标签
                    const tags = [];
                    document.querySelectorAll('span[class*="tag"]').forEach(tag => {
                        const text = tag.textContent;
                        if (text && text.startsWith('#')) {
                            tags.push(text.slice(1));
                        }
                    });
                    
                    return {
                        title: title.trim(),
                        content: content.trim(),
                        author: author.trim(),
                        likes: parseInt(likes) || 0,
                        comments: parseInt(comments) || 0,
                        images: images.slice(0, 9),
                        tags: tags,
                        crawled_at: new Date().toISOString()
                    };
                }
            """)
            return data
        except Exception as e:
            logger.warning(f"[xiaohongshu] 提取帖子详情失败: {e}")
            return {}

    async def close(self):
        """关闭爬虫资源"""
        if self._browser:
            await self._browser.close()
            self._browser = None
