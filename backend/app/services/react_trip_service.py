from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents.react_agent import get_react_agent
from app.models.schemas import AgentStep, ReactTripResponse, TripRequest
from app.services.trip_service import generate_trip_itinerary

logger = logging.getLogger(__name__)

REACT_AGENT_TIMEOUT_SECONDS = 30


def _normalize_agent_steps(raw_steps: list[dict[str, Any]] | None) -> list[AgentStep]:
    """Convert loose agent step dicts into API response models."""
    steps: list[AgentStep] = []
    for raw_step in raw_steps or []:
        steps.append(
            AgentStep(
                step=int(raw_step.get("step", len(steps) + 1)),
                state=raw_step.get("state"),
                thought=raw_step.get("thought"),
                action=raw_step.get("action"),
                observation=raw_step.get("observation"),
                tool_input=raw_step.get("tool_input"),
            )
        )
    return steps


def _run_react_agent_sync(request: TripRequest) -> dict[str, Any]:
    agent = get_react_agent(max_steps=5)
    return agent.run(request)


async def generate_trip_with_react_agent(
    request: TripRequest,
    timeout_seconds: int = REACT_AGENT_TIMEOUT_SECONDS,
) -> ReactTripResponse:
    """
    Run the experimental ReAct chain and fall back to the stable service chain.

    The ReAct path is intentionally isolated from the normal /trip/generate
    route. If it fails or times out, callers still receive a usable itinerary
    from generate_trip_itinerary with fallback_used=True.
    """
    try:
        agent_result = await asyncio.wait_for(
            asyncio.to_thread(_run_react_agent_sync, request),
            timeout=timeout_seconds,
        )

        itinerary = generate_trip_itinerary(request)
        return ReactTripResponse(
            success=True,
            mode="react_agent",
            fallback_used=False,
            itinerary=itinerary,
            react_answer=agent_result.get("final_answer"),
            steps=_normalize_agent_steps(agent_result.get("steps")),
            tool_calls=int(agent_result.get("tool_calls", 0) or 0),
            error=agent_result.get("error"),
        )
    except Exception as agent_error:
        logger.warning("ReAct Agent failed, falling back to stable chain: %s", agent_error)

        try:
            fallback_itinerary = generate_trip_itinerary(request)
        except Exception as fallback_error:
            logger.exception("Stable fallback chain also failed")
            return ReactTripResponse(
                success=False,
                mode="fallback",
                fallback_used=True,
                itinerary=None,
                react_answer="ReAct Agent 执行失败，稳定生成链路也未能返回行程。",
                steps=[],
                tool_calls=0,
                error=f"agent_error={agent_error}; fallback_error={fallback_error}",
            )

        return ReactTripResponse(
            success=True,
            mode="fallback",
            fallback_used=True,
            itinerary=fallback_itinerary,
            react_answer="ReAct Agent 执行失败，已回退到稳定生成链路。",
            steps=[],
            tool_calls=0,
            error=str(agent_error),
        )


def get_available_tools_info() -> list[dict[str, str]]:
    """Return ReAct Agent tool metadata without exposing the agent object."""
    try:
        agent = get_react_agent()
        return agent.get_available_tools()
    except Exception:
        logger.exception("Failed to load ReAct Agent tool metadata")
        return []
