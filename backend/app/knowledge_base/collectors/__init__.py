"""
数据采集模块

支持从多个社交平台采集用户生成内容。
"""

from app.knowledge_base.collectors.base_collector import BaseCollector
from app.knowledge_base.collectors.xiaohongshu_collector import XiaohongshuCollector

__all__ = ["BaseCollector", "XiaohongshuCollector"]
