"""
多模态解析模块

支持图文内容解析、OCR 提取和结构化摘要生成。
"""

from app.knowledge_base.parsers.multimodal_parser import MultimodalParser, StructuredPost

__all__ = ["MultimodalParser", "StructuredPost"]
