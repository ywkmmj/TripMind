import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional, List

from app.models.schemas import (
    Itinerary,
    ReactTripResponse,
    TripDetailResponse,
    TripEditRequest,
    TripListResponse,
    TripRequest,
    TripSaveRequest,
    ItineraryValidationResponse,
)

logger = logging.getLogger(__name__)


def _deep_strip_private_fields(obj: Any) -> Any:
    """递归删除所有以下划线开头的字段（如 _type、__v 等）"""
    if isinstance(obj, dict):
        return {
            k: _deep_strip_private_fields(v)
            for k, v in obj.items()
            if not k.startswith("_")
        }
    if isinstance(obj, list):
        return [_deep_strip_private_fields(item) for item in obj]
    return obj


def _build_cleaned_request(raw_request: dict) -> dict:
    """清理请求数据，只保留 TripRequest 需要的字段"""
    cleaned = _deep_strip_private_fields(raw_request)
    return {
        "destination": cleaned.get("destination"),
        "start_date": cleaned.get("start_date"),
        "end_date": cleaned.get("end_date"),
        "days": cleaned.get("days", 3),
        "travelers": cleaned.get("travelers", 2),
        "budget": cleaned.get("budget", 0),
        "preferences": cleaned.get("preferences", []),
        "pace": cleaned.get("pace"),
        "dietary_preferences": cleaned.get("dietary_preferences", []),
        "hotel_level": cleaned.get("hotel_level"),
        "special_notes": cleaned.get("special_notes"),
    }


from app.services.storage_service import (
    delete_itinerary_by_trip_id,
    get_itinerary_by_trip_id,
    list_saved_itineraries,
    save_itinerary,
)
from app.services.trip_service import (
    edit_trip_itinerary,
    generate_trip_itinerary,
)
from app.services.react_trip_service import (
    generate_trip_with_react_agent,
    get_available_tools_info,
)
from app.services.itinerary_validation_service import (
    get_itinerary_validation_service,
    ValidationResult,
    ValidationIssue,
    ValidationStatus,
)
from app.services.multi_stage_agent import (
    get_pipeline, 
    get_async_task_status, 
    list_async_tasks, 
    clear_async_tasks,
    PipelineMode
)
from app.models.schemas import PipelineResponse, PipelineSummary
from app.services.tracing_service import TracingService


router = APIRouter(prefix="/trip", tags=["trip"])


@router.get("", response_model=TripListResponse)
def list_trips() -> TripListResponse:
    """返回已保存行程的摘要列表。"""
    return list_saved_itineraries()


@router.post("/generate", response_model=Itinerary)
def generate_trip(
    raw_request: dict,
    mode: str = Query(
        "fast", 
        description="执行模式: fast=快速(仅行程规划), async=异步(快速返回+后台补充), full=完整(所有阶段)"
    )
) -> Itinerary:
    # 递归清理请求数据，然后构建 TripRequest
    request = TripRequest(**_build_cleaned_request(raw_request))
    """
    生成结构化 itinerary。
    
    执行模式:
    - fast (默认): 快速模式，仅执行行程规划，最快响应
    - async: 异步模式，快速返回行程后，后台异步补充地图/天气/票价数据
    - full: 完整模式，执行所有阶段
    
    阶段:
    1. 行程规划 (所有模式)
    2. 地图数据补充 (full/async)
    3. 天气检查 (full/async)
    4. 票价检查 (full/async)
    5. 一致性校验 (full/async)
    """
    # 解析模式
    try:
        pipeline_mode = PipelineMode(mode)
    except ValueError:
        pipeline_mode = PipelineMode.FAST
    
    # 创建追踪上下文
    trace_ctx = TracingService.create_trace(
        request_type=f"trip_generation_{pipeline_mode.value}",
        user_request=request.model_dump(),
        destination=request.destination
    )
    
    try:
        # 使用多阶段流水线
        pipeline = get_pipeline()
        
        if pipeline_mode == PipelineMode.ASYNC:
            # 异步模式
            pipeline_result = pipeline.execute_async(request, trace_ctx)
        else:
            # 快速或完整模式
            pipeline_result = pipeline.execute(request, trace_ctx, pipeline_mode)
        
        if not pipeline_result.success:
            # 流水线失败时回退到原方式
            from app.services.trip_service import generate_trip_itinerary
            itinerary = generate_trip_itinerary(request, trace_ctx)
            
            TracingService.finish_trace(
                trace_ctx,
                success=True,
                final_output={
                    "itinerary": itinerary.model_dump(),
                    "fallback": "multi_stage_failed"
                }
            )
            
            return itinerary
        
        # 提取最终的行程
        itinerary = pipeline_result.context.itinerary
        
        if itinerary is None:
            # 如果没有行程，回退
            from app.services.trip_service import generate_trip_itinerary
            itinerary = generate_trip_itinerary(request, trace_ctx)
        
        # 完成追踪
        summary_data = pipeline_result.get_summary()
        TracingService.finish_trace(
            trace_ctx,
            success=pipeline_result.success,
            final_output={
                "itinerary": itinerary.model_dump(),
                "summary": summary_data,
                "mode": pipeline_mode.value
            }
        )
        
        return itinerary
        
    except Exception as e:
        # 出错时回退到原方式
        try:
            from app.services.trip_service import generate_trip_itinerary
            itinerary = generate_trip_itinerary(request, trace_ctx)
            
            TracingService.finish_trace(
                trace_ctx,
                success=True,
                final_output={
                    "itinerary": itinerary.model_dump(),
                    "fallback": "exception"
                }
            )
            
            return itinerary
        except Exception as fallback_e:
            TracingService.finish_trace(
                trace_ctx,
                success=False,
                error_message=str(fallback_e)
            )
            raise


@router.post("/edit", response_model=Itinerary)
def edit_trip(request: TripEditRequest) -> Itinerary:
    """根据用户编辑指令返回更新后的 itinerary。"""
    return edit_trip_itinerary(request)


@router.post("/save")
def save_trip(request: TripSaveRequest) -> dict[str, str]:
    """保存 itinerary，并返回 trip_id。"""
    saved_trip_id = save_itinerary(request.itinerary)
    return {
        "message": "Trip itinerary saved successfully.",
        "trip_id": saved_trip_id,
    }


@router.get("/{trip_id}", response_model=TripDetailResponse)
def get_trip_detail(trip_id: str) -> TripDetailResponse:
    """根据 trip_id 查询已保存 itinerary。"""
    trip_detail = get_itinerary_by_trip_id(trip_id)
    if trip_detail is None:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return trip_detail


@router.delete("/{trip_id}")
def delete_trip(trip_id: str) -> dict[str, str]:
    """根据 trip_id 删除已保存 itinerary。"""
    deleted = delete_itinerary_by_trip_id(trip_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return {
        "message": "Trip itinerary deleted successfully.",
        "trip_id": trip_id,
    }


# ========== ReAct Agent 端点 ==========

@router.post("/generate-react", response_model=ReactTripResponse)
async def generate_trip_react(request: TripRequest) -> ReactTripResponse:
    """
    使用 ReAct Agent 生成旅行规划
    
    这是一个增强版的行程生成，使用思考-行动-观察循环，
    可以调用工具获取更丰富的信息。
    """
    return await generate_trip_with_react_agent(request)


@router.get("/react/tools", response_model=list)
def get_react_tools() -> list:
    """获取 ReAct Agent 可用的工具列表"""
    return get_available_tools_info()


# ========== 行程校验端点 ==========

@router.post("/validate", response_model=ItineraryValidationResponse)
def validate_trip(
    itinerary: Itinerary,
    trip_request: Optional[TripRequest] = None
) -> ItineraryValidationResponse:
    """
    校验行程合理性
    
    检查内容包括：
    - 预算是否合理
    - 景点间距离和交通时间
    - 营业时间
    - 每日行程密度
    """
    validation_service = get_itinerary_validation_service()
    result = validation_service.validate_itinerary(itinerary, trip_request)
    
    # 转换为响应模型
    return _convert_validation_result_to_response(result)


def _convert_validation_result_to_response(result: ValidationResult) -> ItineraryValidationResponse:
    """将校验结果转换为响应模型"""
    from app.models.schemas import ValidationIssueItem, ValidationSummary
    
    issues = [
        ValidationIssueItem(
            type=issue.type.value,
            status=issue.status.value,
            day_index=issue.day_index,
            spot_name=issue.spot_name,
            message=issue.message,
            suggestion=issue.suggestion,
            details=issue.details
        )
        for issue in result.issues
    ]
    
    summary = ValidationSummary(**result.summary)
    
    return ItineraryValidationResponse(
        overall_status=result.overall_status.value,
        issues=issues,
        summary=summary,
        has_errors=result.has_errors(),
        has_warnings=result.has_warnings()
    )


@router.post("/generate-multi-stage", response_model=PipelineResponse)
def generate_trip_multi_stage(
    raw_request: dict,
    mode: str = Query(
        "full", 
        description="执行模式: fast=快速, async=异步, full=完整"
    )
) -> PipelineResponse:
    """
    使用多阶段 Agent 流水线生成行程（返回详细流水线信息）
    
    执行模式:
    - full (默认): 完整模式
    - fast: 快速模式
    - async: 异步模式
    
    阶段:
    1. 行程规划
    2. 地图数据补充
    3. 天气检查
    4. 票价检查
    5. 一致性校验
    """
    # 记录原始请求，用于调试
    logger.info(f"Received raw request keys: {list(raw_request.keys())}")
    
    # 递归清理请求数据，然后构建 TripRequest
    try:
        request = TripRequest(**_build_cleaned_request(raw_request))
        logger.info(f"Successfully parsed TripRequest for destination: {request.destination}")
    except Exception as e:
        logger.error(f"Failed to parse TripRequest: {e}")
        raise
    
    # 解析模式
    try:
        pipeline_mode = PipelineMode(mode)
    except ValueError:
        pipeline_mode = PipelineMode.FULL
    
    # 创建追踪上下文
    trace_ctx = TracingService.create_trace(
        request_type=f"multi_stage_trip_generation_{pipeline_mode.value}",
        user_request=request.model_dump(),
        destination=request.destination
    )
    
    try:
        pipeline = get_pipeline()
        
        if pipeline_mode == PipelineMode.ASYNC:
            pipeline_result = pipeline.execute_async(request, trace_ctx)
        else:
            pipeline_result = pipeline.execute(request, trace_ctx, pipeline_mode)
        
        # 转换结果
        summary_data = pipeline_result.get_summary()
        
        # 完成追踪
        TracingService.finish_trace(
            trace_ctx,
            success=pipeline_result.success,
            final_output={
                "itinerary": pipeline_result.context.itinerary.model_dump() if pipeline_result.context.itinerary else None,
                "summary": summary_data
            }
        )
        
        if pipeline_result.final_error:
            logger.error(f"Pipeline failed with error: {pipeline_result.final_error}")
        
        return PipelineResponse(
            success=pipeline_result.success,
            itinerary=pipeline_result.context.itinerary,
            summary=PipelineSummary(**summary_data),
            final_error=pipeline_result.final_error
        )
        
    except Exception as e:
        logger.exception(f"Exception in generate_trip_multi_stage: {e}")
        TracingService.finish_trace(
            trace_ctx,
            success=False,
            error_message=str(e)
        )
        raise


# ========== 异步任务管理 ==========

@router.get("/async-tasks", tags=["async"])
def get_async_tasks() -> List[Dict[str, Any]]:
    """获取所有异步任务状态"""
    return list_async_tasks()


@router.get("/async-tasks/{task_id}", tags=["async"])
def get_async_task(task_id: str) -> Dict[str, Any]:
    """获取指定异步任务状态"""
    task = get_async_task_status(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Async task not found")
    return task


@router.delete("/async-tasks", tags=["async"])
def clear_async_tasks_endpoint() -> Dict[str, int]:
    """清理已完成的异步任务"""
    cleared = clear_async_tasks()
    return {"cleared_tasks": cleared}
