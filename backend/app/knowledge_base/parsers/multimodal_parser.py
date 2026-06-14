"""
多模态内容解析器

支持多种格式文件的解析和信息提取：
1. JSON 文件：小红书帖子数据
2. 图片文件：使用多模态模型分析
3. PDF 文件：提取文本和图片
4. Word/文档文件：提取文本内容
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# API 常量
DASHSCOPE_MULTIMODAL_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_REQUEST_TIMEOUT = 60  # 秒
DEFAULT_MAX_TOKENS = 1024


@dataclass
class ImageInsight:
    """图片洞察结果"""
    url: str
    description: str = ""
    recognized_spots: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    season_hints: list[str] = field(default_factory=list)
    crowd_level: str = "未知"  # 低/中/高


@dataclass
class StructuredPost:
    """
    结构化后的帖子数据。

    包含从原始帖子提取的所有关键信息，用于知识库构建。
    """
    post_id: str
    platform: str
    author: str
    title: str
    content: str
    destination: str | None
    images: list[ImageInsight]
    publish_time: datetime | None
    likes: int = 0
    comments: int = 0
    tags: list[str] = field(default_factory=list)

    # 结构化摘要
    summary: str = ""
    key_attractions: list[dict[str, str]] = field(default_factory=list)
    food_recommendations: list[dict[str, str]] = field(default_factory=list)
    experience_tips: list[str] = field(default_factory=list)

    # 实用信息
    timing_info: dict[str, str] = field(default_factory=dict)
    budget_estimate: dict[str, Any] = field(default_factory=dict)

    # 元数据
    quality_score: float = 0.0
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "post_id": self.post_id,
            "platform": self.platform,
            "author": self.author,
            "title": self.title,
            "content": self.content,
            "destination": self.destination,
            "images": [
                {
                    "url": img.url,
                    "description": img.description,
                    "recognized_spots": img.recognized_spots,
                    "activities": img.activities,
                    "season_hints": img.season_hints,
                    "crowd_level": img.crowd_level,
                }
                for img in self.images
            ],
            "publish_time": self.publish_time.isoformat() if self.publish_time else None,
            "likes": self.likes,
            "comments": self.comments,
            "tags": self.tags,
            "summary": self.summary,
            "key_attractions": self.key_attractions,
            "food_recommendations": self.food_recommendations,
            "experience_tips": self.experience_tips,
            "timing_info": self.timing_info,
            "budget_estimate": self.budget_estimate,
            "quality_score": self.quality_score,
            "raw_data": self.raw_data,
        }


class MultimodalParser:
    """
    多模态内容解析器。

    支持解析多种格式的文件并提取旅行相关信息：
    - JSON 文件：小红书帖子数据
    - 图片文件（JPG, PNG, GIF）：使用多模态模型分析
    - PDF 文件：提取文本和图片
    - Word/文档文件：提取文本内容

    依赖环境变量：
    - LLM_API_KEY：API 密钥（必需）
    - MULTIMODAL_MODEL_NAME：多模态模型名称（默认 qwen3-vl-flash）
    """

    SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    SUPPORTED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
    SUPPORTED_JSON_EXTENSIONS = {".json"}

    # 图片 MIME 类型映射
    IMAGE_MIME_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    def __init__(self):
        """初始化解析器"""
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.multimodal_model = os.getenv("MULTIMODAL_MODEL_NAME", "qwen3-vl-flash")

        if not self.api_key:
            logger.warning("[multimodal] 未设置 LLM_API_KEY，将使用规则提取而非模型分析")

    async def parse_file(self, filepath: str | Path) -> list[StructuredPost]:
        """
        解析文件并提取结构化信息。

        Args:
            filepath: 文件路径

        Returns:
            结构化帖子列表（可能多个）
        """
        filepath = Path(filepath)
        ext = filepath.suffix.lower()

        if ext in self.SUPPORTED_JSON_EXTENSIONS:
            return await self._parse_json_file(filepath)
        elif ext in self.SUPPORTED_IMAGE_EXTENSIONS:
            return await self._parse_image_file(filepath)
        elif ext in self.SUPPORTED_DOC_EXTENSIONS:
            return await self._parse_doc_file(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")

    async def parse_post(self, raw_post: dict[str, Any]) -> StructuredPost:
        """
        解析单条帖子。

        Args:
            raw_post: 原始帖子数据

        Returns:
            结构化后的帖子数据
        """
        post_id = raw_post.get("post_id") or raw_post.get("id", "unknown")
        platform = raw_post.get("platform", "unknown")

        # 提取基本信息
        title = raw_post.get("title", "") or raw_post.get("desc", "") or ""
        content = raw_post.get("content", "") or raw_post.get("desc", "") or ""

        # 处理图片列表
        raw_images = raw_post.get("images", []) or raw_post.get("image_list", [])
        images = []
        for img_url in raw_images[:9]:
            insight = await self._analyze_single_image(img_url, content)
            images.append(insight)

        # 提取标签
        tags = raw_post.get("tags", [])
        if not tags and content:
            tags = self._extract_hashtags(content)

        # 解析发布时间
        publish_time = self._parse_datetime(raw_post.get("publish_time") or raw_post.get("time"))

        # 提取目的地
        destination = raw_post.get("destination") or self._extract_destination(title + " " + content)

        # 生成结构化摘要
        structured = await self._generate_structured_summary(title, content, images)

        # 构建返回对象
        result = StructuredPost(
            post_id=str(post_id),
            platform=platform,
            author=raw_post.get("author", "") or raw_post.get("nickname", "") or "匿名用户",
            title=title,
            content=content,
            destination=destination,
            images=images,
            publish_time=publish_time,
            likes=int(raw_post.get("likes", 0) or 0),
            comments=int(raw_post.get("comments", 0) or 0),
            tags=tags,
            summary=structured.get("summary", ""),
            key_attractions=structured.get("key_attractions", []),
            food_recommendations=structured.get("food_recommendations", []),
            experience_tips=structured.get("experience_tips", []),
            timing_info=structured.get("timing_info", {}),
            budget_estimate=structured.get("budget_estimate", {}),
            quality_score=0.0,
            raw_data=raw_post,
        )

        return result

    async def parse_batch(self, raw_posts: list[dict[str, Any]]) -> list[StructuredPost]:
        """批量解析帖子"""
        results = []

        for post in raw_posts:
            try:
                structured = await self.parse_post(post)
                results.append(structured)
            except Exception as e:
                logger.warning(f"[multimodal] 帖子解析失败: {e}")
                continue

        logger.info(f"[multimodal] 批量解析完成: {len(results)}/{len(raw_posts)} 条")
        return results

    # ==================== 文件解析方法 ====================

    async def _parse_json_file(self, filepath: Path) -> list[StructuredPost]:
        """解析 JSON 文件"""
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        posts = data if isinstance(data, list) else [data]

        # 为每个帖子补充信息
        for i, post in enumerate(posts):
            if "post_id" not in post:
                post["post_id"] = f"{filepath.stem}_{i + 1}"
            if "platform" not in post:
                post["platform"] = "imported"

        return await self.parse_batch(posts)

    async def _parse_image_file(self, filepath: Path) -> list[StructuredPost]:
        """解析图片文件"""
        # 使用多模态模型分析图片
        insight = await self._analyze_local_image(filepath)

        # 直接构建结构化对象，避免重复分析
        structured = StructuredPost(
            post_id=filepath.stem,
            title=f"旅行照片 - {filepath.name}",
            content=insight.description,
            platform="image_upload",
            author="用户上传",
            images=[insight],
            destination=insight.recognized_spots[0] if insight.recognized_spots else None,
            publish_time=None,
            likes=0,
            comments=0,
            tags=insight.recognized_spots,
            key_attractions=[{"name": spot, "highlight": ""} for spot in insight.recognized_spots] if insight.recognized_spots else [],
        )

        return [structured]

    async def _parse_doc_file(self, filepath: Path) -> list[StructuredPost]:
        """解析文档文件（PDF/Word/TXT）"""
        content = ""

        if filepath.suffix.lower() == ".pdf":
            content = self._extract_text_from_pdf(filepath)
        elif filepath.suffix.lower() in {".doc", ".docx"}:
            content = self._extract_text_from_word(filepath)
        else:  # .txt
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

        post = {
            "post_id": filepath.stem,
            "title": content[:50].strip() or f"文档 - {filepath.name}",
            "content": content,
            "platform": "document_upload",
            "author": "用户上传",
            "images": [],
            "likes": 0,
            "comments": 0,
            "tags": [],
        }

        structured = await self.parse_post(post)
        return [structured]

    # ==================== 图片分析方法 ====================

    async def _analyze_single_image(self, image_url: str, context: str = "") -> ImageInsight:
        """
        分析单张图片（URL）。

        Args:
            image_url: 图片 URL
            context: 上下文文本

        Returns:
            图片洞察结果
        """
        insight = ImageInsight(url=image_url)

        if not self.api_key:
            return insight

        try:
            analysis = await self._call_multimodal_model(image_url, context)
            if analysis:
                insight.description = analysis.get("description", "")
                insight.recognized_spots = analysis.get("spots", [])
                insight.activities = analysis.get("activities", [])
                insight.season_hints = analysis.get("season_hints", [])
                insight.crowd_level = analysis.get("crowd_level", "未知")
        except Exception as e:
            logger.warning(f"[multimodal] 图片分析失败 {image_url}: {e}")

        return insight

    async def _analyze_local_image(self, filepath: Path) -> ImageInsight:
        """
        分析本地图片文件。

        Args:
            filepath: 本地图片路径

        Returns:
            图片洞察结果
        """
        insight = ImageInsight(url=str(filepath))

        if not self.api_key:
            return insight

        try:
            # 读取图片并编码为 base64，根据文件扩展名选择正确的 MIME 类型
            ext = filepath.suffix.lower()
            mime_type = self.IMAGE_MIME_TYPES.get(ext, "image/jpeg")
            with open(filepath, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode()

            # 调用多模态模型分析
            analysis = await self._call_multimodal_model_base64(image_base64, "", mime_type)
            if analysis:
                insight.description = analysis.get("description", "")
                insight.recognized_spots = analysis.get("spots", [])
                insight.activities = analysis.get("activities", [])
                insight.season_hints = analysis.get("season_hints", [])
                insight.crowd_level = analysis.get("crowd_level", "未知")
        except Exception as e:
            logger.warning(f"[multimodal] 本地图片分析失败 {filepath}: {e}")

        return insight

    async def _call_multimodal_model(self, image_url: str, context: str) -> dict[str, Any] | None:
        """调用多模态模型分析图片（URL 方式）"""
        if not self.api_key:
            return None

        try:
            import httpx

            # 构建请求
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            prompt = f"""
请分析这张旅行图片，提取以下信息：
1. 图片描述（详细描述图片中的内容）
2. 识别出的景点或地标
3. 可能的活动类型（如拍照、徒步、用餐等）
4. 季节特征（如有）
5. 人流估计（低/中/高）

上下文：{context[:200] if context else '无'}

请以 JSON 格式返回，包含这些字段：
{{
    "description": "图片描述文本",
    "spots": ["景点1", "景点2"],
    "activities": ["活动1", "活动2"],
    "season_hints": ["季节特征1"],
    "crowd_level": "低/中/高"
}}

请确保返回有效的 JSON，不要包含其他内容。
"""

            # DashScope 多模态 API 格式（使用 messages 格式）
            data = {
                "model": self.multimodal_model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"image": image_url},
                                {"text": prompt}
                            ]
                        }
                    ]
                },
                "parameters": {
                    "max_tokens": DEFAULT_MAX_TOKENS,
                },
            }

            logger.info(f"[multimodal] 调用 DashScope 多模态模型 {self.multimodal_model}")

            async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT) as client:
                response = await client.post(DASHSCOPE_MULTIMODAL_API_URL, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()

            # 解析 DashScope 多模态响应，增强容错
            if not result or not isinstance(result, dict):
                logger.warning(f"[multimodal] 响应为空或格式不正确: {result}")
                return None
                
            output = result.get("output", {})
            if not output or not isinstance(output, dict):
                logger.warning(f"[multimodal] output 字段为空或格式不正确: {result}")
                return None
                
            choices = output.get("choices", [])
            if not choices or not isinstance(choices, list) or len(choices) == 0:
                logger.warning(f"[multimodal] choices 字段为空或格式不正确: {result}")
                return None
                
            choice = choices[0]
            if not choice or not isinstance(choice, dict):
                logger.warning(f"[multimodal] choice 为空或格式不正确: {result}")
                return None
                
            message = choice.get("message", {})
            if not message or not isinstance(message, dict):
                logger.warning(f"[multimodal] message 为空或格式不正确: {result}")
                return None
                
            content_value = message.get("content")
            if content_value is None:
                logger.warning(f"[multimodal] content 为空: {result}")
                return None
                
            # content 可能是字符串或列表
            if isinstance(content_value, list):
                content_parts = []
                for part in content_value:
                    if isinstance(part, dict) and "text" in part:
                        content_parts.append(part["text"])
                content = "\n".join(content_parts)
            else:
                content = str(content_value)
            
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"description": content, "spots": [], "activities": [], "season_hints": [], "crowd_level": "未知"}

        except Exception as e:
            logger.warning(f"[multimodal] 多模态模型调用失败: {e}")
            return None

    async def _call_multimodal_model_base64(self, image_base64: str, context: str, mime_type: str = "image/jpeg") -> dict[str, Any] | None:
        """调用多模态模型分析图片（base64 方式）"""
        return await self._call_multimodal_model(f"data:{mime_type};base64,{image_base64}", context)

    # ==================== 文档文本提取方法 ====================

    def _extract_text_from_pdf(self, filepath: Path) -> str:
        """从 PDF 中提取文本"""
        try:
            import PyPDF2

            text = ""
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""

            return text
        except ImportError:
            logger.warning("[multimodal] 未安装 PyPDF2，请安装: pip install PyPDF2")
            return ""
        except Exception as e:
            logger.warning(f"[multimodal] PDF 文本提取失败: {e}")
            return ""

    def _extract_text_from_word(self, filepath: Path) -> str:
        """从 Word 文档中提取文本"""
        try:
            from docx import Document

            doc = Document(filepath)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text
        except ImportError:
            logger.warning("[multimodal] 未安装 python-docx，请安装: pip install python-docx")
            return ""
        except Exception as e:
            logger.warning(f"[multimodal] Word 文档文本提取失败: {e}")
            return ""

    # ==================== 结构化摘要生成 ====================

    async def _generate_structured_summary(
        self,
        title: str,
        content: str,
        images: list[ImageInsight],
    ) -> dict[str, Any]:
        """生成结构化摘要 - 使用规则提取，LLM 调用待实现"""
        result = {
            "summary": "",
            "key_attractions": [],
            "food_recommendations": [],
            "experience_tips": [],
            "timing_info": {},
            "budget_estimate": {},
        }

        # 直接使用规则提取
        return self._rule_based_extraction(title, content, images)

    def _build_summary_prompt(self, title: str, content: str, images: list[ImageInsight]) -> str:
        """构建摘要生成提示词"""
        image_descs = "\n".join([f"- {img.description}" for img in images if img.description])

        return f"""
请分析以下旅行帖子内容，生成结构化摘要。

标题：{title}

正文：{content[:2000]}

图片描述：
{image_descs if image_descs else '无图片'}

请提取并返回以下信息（JSON格式）：
{{
    "summary": "整体概要（100字内）",
    "key_attractions": [
        {{"name": "景点名", "highlight": "亮点", "tips": "建议"}}
    ],
    "food_recommendations": [
        {{"name": "店名", "dish": "推荐菜", "price": "预算参考"}}
    ],
    "experience_tips": ["tip1", "tip2"],
    "timing_info": {{"best_time": "", "duration": "", "season": ""}},
    "budget_estimate": {{"range": [min, max], "breakdown": {{}}}}
}}

请只返回 JSON，不要有其他内容。
"""

    def _rule_based_extraction(
        self,
        title: str,
        content: str,
        images: list[ImageInsight],
    ) -> dict[str, Any]:
        """基于规则的内容提取"""
        # 合并标题和正文进行分析
        full_text = f"{title}\n{content}"

        # 提取景点
        attractions = self._extract_attractions(full_text)

        # 添加从图片中识别的景点
        for img in images:
            for spot in img.recognized_spots:
                if not any(a.get("name") == spot for a in attractions):
                    attractions.append({"name": spot, "highlight": "", "tips": ""})

        # 提取美食
        foods = self._extract_foods(full_text)

        # 提取 Tips
        tips = self._extract_tips(full_text)

        # 提取时间信息
        timing = self._extract_timing_info(full_text)

        return {
            "summary": content[:200] + "..." if len(content) > 200 else content,
            "key_attractions": attractions[:5],
            "food_recommendations": foods[:5],
            "experience_tips": tips[:5],
            "timing_info": timing,
            "budget_estimate": {},
        }

    def _extract_attractions(self, text: str) -> list[dict[str, str]]:
        """
        提取景点信息
        注意：当前仅支持西安相关景点，如需扩展请添加更多城市关键词
        """
        attractions = []

        known_spots = {
            "兵马俑": "秦始皇兵马俑博物馆",
            "城墙": "西安城墙",
            "大雁塔": "大雁塔",
            "回民街": "回民街美食街",
            "钟楼": "西安钟楼",
            "鼓楼": "西安鼓楼",
            "大唐不夜城": "大唐不夜城",
            "华山": "华山",
            "碑林": "西安碑林博物馆",
        }

        for keyword, name in known_spots.items():
            if keyword in text:
                attractions.append({
                    "name": name,
                    "highlight": f"包含关键词：{keyword}",
                    "tips": "建议提前了解开放时间和门票信息",
                })

        return attractions

    def _extract_foods(self, text: str) -> list[dict[str, str]]:
        """
        提取美食信息
        注意：当前仅支持西安相关美食，如需扩展请添加更多城市美食
        """
        foods = []

        known_foods = {
            "肉夹馍": "西安特色肉夹馍",
            "羊肉泡馍": "西安经典美食",
            "凉皮": "西安凉皮",
            "biangbiang面": "关中特色面食",
            "甑糕": "西安传统甜品",
            "酸梅汤": "西安特色饮品",
            "胡辣汤": "西安早餐推荐",
            "灌汤包": "西安小吃",
        }

        for keyword, name in known_foods.items():
            if keyword in text:
                foods.append({
                    "name": name,
                    "dish": keyword,
                    "price": "参考价格：15-50元",
                })

        return foods

    def _extract_tips(self, text: str) -> list[str]:
        """提取实用 Tips"""
        tips = []

        tip_patterns = [
            (r"建议\s*[：:]\s*(.+?)(?:\n|$)", "建议：{}"),
            (r"注意\s*[：:]\s*(.+?)(?:\n|$)", "注意：{}"),
            (r"避坑\s*[：:]\s*(.+?)(?:\n|$)", "避坑：{}"),
            (r"推荐\s*[：:]\s*(.+?)(?:\n|$)", "推荐：{}"),
        ]

        for pattern, template in tip_patterns:
            matches = re.findall(pattern, text)
            for match in matches[:2]:
                tip_text = match.strip()
                if tip_text and len(tip_text) < 100:
                    tips.append(template.format(tip_text))

        return list(set(tips))

    def _extract_timing_info(self, text: str) -> dict[str, str]:
        """提取时间信息"""
        timing = {}

        time_patterns = [
            (r"(\d+)[月]\s*最适合", "best_time"),
            (r"最佳季节\s*[是]?\s*(\w+)", "season"),
            (r"建议游玩\s*(\d+)\s*[天日]", "duration"),
        ]

        for pattern, key in time_patterns:
            match = re.search(pattern, text)
            if match:
                timing[key] = match.group(1)

        return timing

    # ==================== 辅助方法 ====================

    def _extract_hashtags(self, content: str) -> list[str]:
        """提取话题标签"""
        hashtags = re.findall(r"#(\w+)", content)
        return list(set(hashtags))

    def _extract_destination(self, text: str) -> str | None:
        """提取目的地"""
        known_destinations = [
            "西安", "大理", "丽江", "杭州", "成都", "重庆", "厦门", "三亚",
            "北京", "上海", "广州", "深圳", "苏州", "南京", "青岛", "长沙",
        ]

        for dest in known_destinations:
            if dest in text:
                return dest
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        """解析日期时间"""
        if not value:
            return None

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            try:
                formats = [
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                    "%Y/%m/%d %H:%M:%S",
                    "%Y/%m/%d",
                ]
                for fmt in formats:
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
            except Exception:
                pass

        return None
