from __future__ import annotations

import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from app.mcp.langchain_agent import get_trip_planner_agent


async def main():
    print("=== Testing LangChain Agent Integration ===")
    print()

    print("Step 1: Creating agent instance...")
    agent = get_trip_planner_agent()
    print("  Agent instance created:", type(agent).__name__)
    print()

    print("Step 2: Initializing agent...")
    try:
        await agent.initialize()
        print("  Agent initialized successfully")
        print()

        print("Step 3: Getting available tools...")
        tools = agent.get_available_tools()
        print(f"  Found {len(tools)} tools:")
        for tool in tools:
            print(f"    - {tool['name']}: {tool['description'][:30]}...")
        print()

        print("Step 4: Testing chat functionality...")
        result = await agent.chat("Hello!")
        print("  Chat response received")
        print()

        print("Step 5: Closing agent...")
        await agent.close()
        print("  Agent closed")
        print()

        print("=== All tests passed! ===")

    except Exception as e:
        print(f"  Error: {str(e)}")
        print("=== Test failed ===")


if __name__ == "__main__":
    asyncio.run(main())