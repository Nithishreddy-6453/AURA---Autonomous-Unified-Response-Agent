import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from backend.llm.router import get_llm_provider
from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.tools.browser.browser_session import BrowserSession
from backend.tools import get_default_tool_registry

load_dotenv()


async def run_autonomous_workflow(user_goal: str):
    print("=" * 80)
    print("AURA AUTONOMOUS INVOICE WORKFLOW TRACE")
    print("=" * 80)
    print(f"GOAL:\n  {user_goal}\n")

    # Ensure browser is in headless or headed mode depending on environment
    headless = os.getenv("BROWSER_HEADLESS", "false").strip().lower() in ("true", "1", "yes")
    session = BrowserSession(headless=headless)
    tool_registry = get_default_tool_registry(browser_session=session)
    llm = get_llm_provider()
    planner = Planner(llm_provider=llm, tool_registry=tool_registry)

    step_counter = 1

    def handle_state_change(new_state: AgentState, t: Task):
        print(f"\n--- STATE TRANSITION: {new_state.value} ---")

    def handle_action(action: Action):
        nonlocal step_counter
        print(f"\n[ACTION {step_counter}] -> Tool: '{action.tool_name}'")
        print(f"  Arguments: {json.dumps(action.arguments, indent=2)}")

    def handle_observation(action: Action, obs: Observation):
        nonlocal step_counter
        print(f"[OBSERVATION {step_counter}] -> Success: {obs.success}")
        if obs.success:
            # Print a concise representation of the result
            if isinstance(obs.result, dict):
                # Format file search or read results cleanly
                res_copy = {}
                for k, v in obs.result.items():
                    if k == "content" and isinstance(v, str):
                        res_copy[k] = v[:200] + ("..." if len(v) > 200 else "")
                    elif k == "visible_text_summary" and isinstance(v, str):
                        res_copy[k] = v[:200] + ("..." if len(v) > 200 else "")
                    elif k == "interactive_controls" and isinstance(v, list):
                        res_copy[k] = f"[{len(v)} interactive elements]"
                    else:
                        res_copy[k] = v
                print(f"  Result: {json.dumps(res_copy, indent=2)}")
            else:
                print(f"  Result: {obs.result}")
        else:
            print(f"  Error: {obs.error}")
        step_counter += 1

    runtime = AgentRuntime(
        llm_provider=llm,
        tool_registry=tool_registry,
        planner=planner,
        on_state_change=handle_state_change,
        on_action=handle_action,
        on_observation=handle_observation,
        max_dynamic_steps=15,
    )

    task = Task(user_goal=user_goal)

    try:
        final_task = await runtime.execute_task(task, use_dynamic_adaptation=True)

        print("\n" + "=" * 80)
        print(f"FINAL STATE: {runtime.state.value} | TASK STATUS: {final_task.status.value}")
        if final_task.metadata.get("completion_summary"):
            print(f"COMPLETION SUMMARY: {final_task.metadata['completion_summary']}")
        if final_task.metadata.get("error"):
            print(f"FAILURE ERROR: {final_task.metadata['error']}")
        print("=" * 80)
        return final_task
    finally:
        await session.close()


if __name__ == "__main__":
    goal = "Find the latest Acme invoice and enter it into the Finance Portal."
    result_task = asyncio.run(run_autonomous_workflow(goal))
    if result_task.status != TaskStatus.COMPLETED:
        sys.exit(1)
