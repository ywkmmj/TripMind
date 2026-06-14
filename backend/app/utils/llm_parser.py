"""LLM 输出解析增强模块

提供更严格的 schema 校验、失败重试和可观测日志功能
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type, Union
from dataclasses import dataclass
from enum import Enum
from functools import wraps
import time

logger = logging.getLogger(__name__)


class ParseStatus(Enum):
    """解析状态枚举"""
    SUCCESS = "success"
    INVALID_JSON = "invalid_json"
    SCHEMA_MISMATCH = "schema_mismatch"
    REQUIRED_FIELD_MISSING = "required_field_missing"
    FIELD_TYPE_ERROR = "field_type_error"
    RETRY_EXHAUSTED = "retry_exhausted"


@dataclass
class ParseResult:
    """解析结果封装"""
    status: ParseStatus
    data: Optional[Any] = None
    error_message: Optional[str] = None
    raw_output: Optional[str] = None
    attempts: int = 1
    duration_ms: float = 0.0
    validation_errors: Optional[List[str]] = None

    def is_success(self) -> bool:
        """判断是否成功"""
        return self.status == ParseStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "status": self.status.value,
            "data": self.data,
            "error_message": self.error_message,
            "raw_output": self.raw_output,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
            "validation_errors": self.validation_errors,
        }


def validate_schema(data: Any, schema: Dict[str, Any]) -> List[str]:
    """验证数据是否符合指定的 schema

    Args:
        data: 待验证的数据
        schema: Schema 定义，格式如下：
            {
                "type": "object",
                "properties": {
                    "field1": {"type": "string", "required": True},
                    "field2": {"type": "integer", "required": False, "default": 0},
                    "field3": {"type": "array", "items": {"type": "string"}}
                }
            }

    Returns:
        验证错误列表，空列表表示验证通过
    """
    errors = []

    # 验证根对象类型
    if schema.get("type") == "object" and not isinstance(data, dict):
        errors.append(f"Expected object, got {type(data).__name__}")
        return errors

    # 验证属性
    properties = schema.get("properties", {})
    for field_name, field_schema in properties.items():
        required = field_schema.get("required", False)
        expected_type = field_schema.get("type")

        # 检查是否缺失必需字段
        if required and field_name not in data:
            errors.append(f"Missing required field: {field_name}")
            continue

        # 跳过非必需且缺失的字段
        if field_name not in data:
            continue

        value = data[field_name]

        # 验证类型
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Field {field_name} should be string, got {type(value).__name__}")
        elif expected_type == "integer" and not isinstance(value, int):
            errors.append(f"Field {field_name} should be integer, got {type(value).__name__}")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"Field {field_name} should be number, got {type(value).__name__}")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Field {field_name} should be boolean, got {type(value).__name__}")
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(f"Field {field_name} should be array, got {type(value).__name__}")
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(f"Field {field_name} should be object, got {type(value).__name__}")

        # 验证数组项类型
        if expected_type == "array" and isinstance(value, list):
            item_type = field_schema.get("items", {}).get("type")
            if item_type:
                for i, item in enumerate(value):
                    if item_type == "string" and not isinstance(item, str):
                        errors.append(f"Field {field_name}[{i}] should be string, got {type(item).__name__}")
                    elif item_type == "integer" and not isinstance(item, int):
                        errors.append(f"Field {field_name}[{i}] should be integer, got {type(item).__name__}")
                    elif item_type == "object" and not isinstance(item, dict):
                        errors.append(f"Field {field_name}[{i}] should be object, got {type(item).__name__}")

        # 递归验证嵌套对象
        if expected_type == "object" and isinstance(value, dict):
            nested_schema = field_schema.get("properties", {})
            if nested_schema:
                nested_errors = validate_schema(value, {"type": "object", "properties": nested_schema})
                errors.extend([f"{field_name}.{err}" for err in nested_errors])

    return errors


def extract_json_from_text(text: str) -> Optional[str]:
    """从文本中尝试提取 JSON

    Args:
        text: 包含 JSON 的文本

    Returns:
        提取的 JSON 字符串，或 None 如果无法提取
    """
    # 方法 1: 查找第一个 { 到最后一个 } 之间的内容
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and start < end:
            return text[start:end+1]
    except Exception:
        pass

    # 方法 2: 使用正则表达式查找 JSON 对象
    try:
        pattern = r'\{[^{}]*\}'
        matches = re.findall(pattern, text)
        if matches:
            # 尝试解析每个匹配项
            for match in matches:
                try:
                    json.loads(match)
                    return match
                except Exception:
                    continue
    except Exception:
        pass

    # 方法 3: 查找第一个 [ 到最后一个 ] 之间的内容（数组）
    try:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and start < end:
            return text[start:end+1]
    except Exception:
        pass

    return None


def parse_llm_output(
    llm_output: str,
    schema: Optional[Dict[str, Any]] = None,
    fallback_value: Optional[Any] = None,
) -> ParseResult:
    """解析 LLM 输出

    Args:
        llm_output: LLM 原始输出
        schema: 可选的 schema 用于验证
        fallback_value: 解析失败时的回退值

    Returns:
        ParseResult 对象
    """
    start_time = time.time()
    validation_errors = []

    try:
        # 步骤 1: 尝试直接解析 JSON
        try:
            parsed_data = json.loads(llm_output)
        except json.JSONDecodeError:
            # 步骤 2: 尝试从文本中提取 JSON
            extracted_json = extract_json_from_text(llm_output)
            if extracted_json:
                try:
                    parsed_data = json.loads(extracted_json)
                except json.JSONDecodeError:
                    return ParseResult(
                        status=ParseStatus.INVALID_JSON,
                        error_message="Failed to parse extracted JSON",
                        raw_output=llm_output,
                        duration_ms=(time.time() - start_time) * 1000,
                    )
            else:
                return ParseResult(
                    status=ParseStatus.INVALID_JSON,
                    error_message="No valid JSON found in output",
                    raw_output=llm_output,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # 步骤 3: 验证 Schema（如果提供）
        if schema:
            validation_errors = validate_schema(parsed_data, schema)
            if validation_errors:
                return ParseResult(
                    status=ParseStatus.SCHEMA_MISMATCH,
                    error_message="Schema validation failed",
                    data=parsed_data,
                    raw_output=llm_output,
                    validation_errors=validation_errors,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # 成功！
        return ParseResult(
            status=ParseStatus.SUCCESS,
            data=parsed_data,
            raw_output=llm_output,
            duration_ms=(time.time() - start_time) * 1000,
        )

    except Exception as e:
        return ParseResult(
            status=ParseStatus.UNKNOWN_ERROR if hasattr(ParseStatus, "UNKNOWN_ERROR") else ParseStatus.INVALID_JSON,
            error_message=f"Unexpected error: {str(e)}",
            raw_output=llm_output,
            duration_ms=(time.time() - start_time) * 1000,
        )


def llm_parser_with_retry(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    schema: Optional[Dict[str, Any]] = None,
    fallback_value: Optional[Any] = None,
    log_all_attempts: bool = True,
):
    """LLM 解析装饰器，带重试功能

    Args:
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        schema: 可选的 schema 用于验证
        fallback_value: 最终失败时的回退值
        log_all_attempts: 是否记录所有尝试

    Returns:
        装饰器函数
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            overall_start = time.time()
            last_result: Optional[ParseResult] = None

            for attempt in range(1, max_retries + 1):
                attempt_start = time.time()

                try:
                    # 调用原始函数获取 LLM 输出
                    llm_output = func(*args, **kwargs)

                    # 解析输出
                    result = parse_llm_output(llm_output, schema, fallback_value)
                    result.attempts = attempt
                    last_result = result

                    # 记录日志
                    if log_all_attempts or not result.is_success():
                        logger.info(
                            f"LLM parsing attempt {attempt}/{max_retries}: "
                            f"status={result.status.value}, "
                            f"duration={(time.time() - attempt_start)*1000:.2f}ms"
                        )
                        if not result.is_success():
                            logger.warning(
                                f"Parsing failed: {result.error_message}, "
                                f"validation_errors={result.validation_errors}"
                            )

                    # 如果成功，直接返回
                    if result.is_success():
                        result.duration_ms = (time.time() - overall_start) * 1000
                        return result

                except Exception as e:
                    logger.error(
                        f"LLM call failed on attempt {attempt}/{max_retries}: {str(e)}"
                    )
                    last_result = ParseResult(
                        status=ParseStatus.INVALID_JSON,
                        error_message=f"LLM call failed: {str(e)}",
                        attempts=attempt,
                    )

                # 不是最后一次尝试时，等待后重试
                if attempt < max_retries:
                    time.sleep(retry_delay)

            # 所有尝试都失败了
            logger.error(f"All {max_retries} parsing attempts failed")
            if last_result:
                last_result.status = ParseStatus.RETRY_EXHAUSTED
                last_result.duration_ms = (time.time() - overall_start) * 1000
                last_result.data = fallback_value
                return last_result

            return ParseResult(
                status=ParseStatus.RETRY_EXHAUSTED,
                error_message=f"All {max_retries} attempts failed",
                data=fallback_value,
                duration_ms=(time.time() - overall_start) * 1000,
            )

        return wrapper
    return decorator


# 预定义的常用 Schema，匹配项目实际使用的结构
PLANNER_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "required": True},
        "tips": {"type": "array", "items": {"type": "string"}},
        "days": {
            "type": "array",
            "required": True,
            "items": {
                "type": "object",
                "properties": {
                    "day_index": {"type": "integer", "required": True},
                    "theme": {"type": "string", "required": True},
                    "spot_name": {"type": "string", "required": True},
                    "spot_description": {"type": "string", "required": True},
                    "meal_name": {"type": "string", "required": True},
                    "meal_notes": {"type": "string", "required": True},
                    "daily_note": {"type": "string", "required": True},
                }
            }
        }
    }
}

DAY_EDIT_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "theme": {"type": "string", "required": True},
        "spot_name": {"type": "string", "required": True},
        "spot_description": {"type": "string", "required": True},
        "meal_name": {"type": "string", "required": True},
        "meal_notes": {"type": "string", "required": True},
        "daily_note": {"type": "string", "required": True},
    }
}

