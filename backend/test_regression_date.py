import asyncio
import os
import sys
from backend.llm.router import get_llm_provider
from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.models.task import Task, TaskStatus
from backend.tools.browser.browser_session import BrowserSession
from backend.tools import get_default_tool_registry

async def run_regression_test():
    print("=" * 80)
    print("REGRESSION TEST: DATE HANDLING AND RECOVERY")
    print("=" * 80)

    headless = os.getenv("BROWSER_HEADLESS", "false").strip().lower() in ("true", "1", "yes")
    session = BrowserSession(headless=headless)
    tool_registry = get_default_tool_registry(browser_session=session)
    llm = get_llm_provider()
    planner = Planner(llm_provider=llm, tool_registry=tool_registry)

    def handle_state_change(new_state: AgentState, t: Task):
        print(f"\n--- STATE TRANSITION: {new_state.value} ---")
        
    def handle_action(action):
        print(f"[ACTION] {action.tool_name} with {action.arguments}")
        
    def handle_observation(action, obs):
        if not obs.success:
            print(f"[OBSERVATION ERROR] {obs.error}")
        else:
            print(f"[OBSERVATION SUCCESS] {str(obs.result)[:100]}")

    class FailingVerifier:
        def __init__(self, real_verifier):
            self.real_verifier = real_verifier
            self.calls = 0

        async def verify(self, metadata, extracted_data):
            self.calls += 1
            if self.calls == 1:
                return __import__("backend.verification.verifier", fromlist=["VerificationResult"]).VerificationResult(
                    False, "Data mismatch: invoice_date: expected '2026-03-20', got '2026-10-05'"
                )
            return await self.real_verifier.verify(metadata, extracted_data)

    runtime = AgentRuntime(
        llm_provider=llm,
        tool_registry=tool_registry,
        planner=planner,
        on_state_change=handle_state_change,
        on_action=handle_action,
        on_observation=handle_observation,
        max_dynamic_steps=20,
    )
    runtime.finance_verifier = FailingVerifier(runtime.finance_verifier)

    goal = "Find the latest Acme invoice and enter ALL its details (invoice_id, company, invoice_date, amount, due_date) into the Finance Portal."
    task = Task(user_goal=goal)

    try:
        final_task = await runtime.execute_task(task, use_dynamic_adaptation=True)
        print("\nFINAL STATE:", runtime.state.value)
        return final_task
    finally:
        await session.close()

if __name__ == "__main__":
    result = asyncio.run(run_regression_test())
    if result.status != TaskStatus.COMPLETED:
        print("Regression test failed!")
        sys.exit(1)
    print("Regression test passed.")
