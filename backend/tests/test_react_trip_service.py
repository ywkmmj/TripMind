from datetime import date
from pathlib import Path
import sys

import pytest


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.services.react_trip_service as react_trip_service  # noqa: E402
from app.models.schemas import BudgetBreakdown, Itinerary, TripRequest  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_trip_request() -> TripRequest:
    return TripRequest(
        destination="大理",
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 12),
        days=3,
        travelers=2,
        budget=3200,
        preferences=["自然风景", "拍照"],
        pace="轻松",
    )


def build_itinerary() -> Itinerary:
    return Itinerary(
        trip_id="trip_test",
        destination="大理",
        summary="测试行程",
        days=[],
        estimated_budget=0,
        budget_breakdown=BudgetBreakdown(),
        tips=[],
        source_notes=[],
    )


@pytest.mark.anyio
async def test_react_trip_success_returns_agent_mode(monkeypatch) -> None:
    def fake_run_agent(request: TripRequest) -> dict:
        return {
            "success": True,
            "final_answer": "已完成 ReAct 规划。",
            "steps": [
                {
                    "step": 1,
                    "state": "thinking",
                    "thought": "需要检索攻略。",
                    "action": None,
                    "observation": None,
                    "tool_input": None,
                }
            ],
            "tool_calls": 1,
            "error": None,
        }

    monkeypatch.setattr(react_trip_service, "_run_react_agent_sync", fake_run_agent)
    monkeypatch.setattr(react_trip_service, "generate_trip_itinerary", lambda request: build_itinerary())

    result = await react_trip_service.generate_trip_with_react_agent(build_trip_request())

    assert result.success is True
    assert result.mode == "react_agent"
    assert result.fallback_used is False
    assert result.itinerary is not None
    assert result.tool_calls == 1
    assert result.steps[0].state == "thinking"


@pytest.mark.anyio
async def test_react_trip_falls_back_when_agent_failed(monkeypatch) -> None:
    def fake_run_agent(request: TripRequest) -> dict:
        raise RuntimeError("agent failed")

    monkeypatch.setattr(react_trip_service, "_run_react_agent_sync", fake_run_agent)
    monkeypatch.setattr(react_trip_service, "generate_trip_itinerary", lambda request: build_itinerary())

    result = await react_trip_service.generate_trip_with_react_agent(build_trip_request())

    assert result.success is True
    assert result.mode == "fallback"
    assert result.fallback_used is True
    assert result.itinerary is not None
    assert "agent failed" in (result.error or "")
