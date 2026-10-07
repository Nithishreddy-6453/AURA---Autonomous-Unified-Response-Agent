import asyncio
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.schemas import NextActionResponseSchema, PlanActionSchema
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry
from backend.tools.browser.browser_session import BrowserSession
from backend.tools.browser.browser_navigate import BrowserNavigateTool
from backend.tools.browser.browser_read import BrowserReadTool
from backend.tools.browser.browser_type import BrowserTypeTool
from backend.tools.browser.browser_click import BrowserClickTool


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_page.html"
LOCAL_TEST_URL = FIXTURE_PATH.resolve().as_uri()


class SequenceMockLLM(LLMProvider):
    """Deterministic LLM mock returning a programmed sequence of planning responses."""

    def __init__(self, initial_plan: dict, step_responses: List[dict]):
        self.initial_plan = initial_plan
        self.step_responses = step_responses
        self.step_index = 0
        self.prompts_received = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        self.prompts_received.append(prompt)
        # Check if initial planning prompt
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps(self.initial_plan)

        if self.step_index < len(self.step_responses):
            resp = self.step_responses[self.step_index]
            self.step_index += 1
            return json.dumps(resp)

        return json.dumps({
            "is_complete": True,
            "completion_summary": "Default completed.",
            "action": None
        })

    async def chat(self, messages: list, temperature: float = 0.0, **kwargs: Any) -> str:
        return ""


class DummyValidationFailingTool(Tool):
    """Tool that fails with a validation error on the first invocation, then succeeds."""

    def __init__(self):
        self.attempts = 0

    @property
    def name(self) -> str:
        return "save_invoice_tool"

    @property
    def description(self) -> str:
        return "Simulates invoice submission requiring validation."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "due_date_present": {"type": "boolean"}
            }
        }

    async def execute(self, **kwargs: Any) -> Observation:
        self.attempts += 1
        has_due_date = kwargs.get("due_date_present", False)
        if not has_due_date:
            return Observation(
                action_id="save-attempt",
                success=False,
                error="Validation error: 'due_date' is required before saving invoice.",
            )
        return Observation(
            action_id="save-attempt",
            success=True,
            result={"status": "Invoice saved successfully"},
        )


class DummyPersistentFailingTool(Tool):
    """Tool that always fails for testing bounded budget exhaustion."""

    @property
    def name(self) -> str:
        return "persistent_failing_tool"

    @property
    def description(self) -> str:
        return "Always fails for budget exhaustion testing."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object"}

    async def execute(self, **kwargs: Any) -> Observation:
        return Observation(
            action_id="failing-step",
            success=False,
            error="Connection timeout to remote service.",
        )


class TestAdaptivePlanning(unittest.TestCase):
    """Tests proving adaptive observation and re-planning behavior in AURA."""

    def test_successful_adaptive_loop(self):
        """Test A: Full adaptive loop: navigate -> observe -> type -> click -> complete."""
        async def run_test():
            session = BrowserSession(headless=True)
            registry = ToolRegistry()
            registry.register(BrowserNavigateTool(session=session))
            registry.register(BrowserReadTool(session=session))
            registry.register(BrowserTypeTool(session=session))
            registry.register(BrowserClickTool(session=session))

            initial_plan = {
                "goal": "Test adaptive form interaction",
                "is_feasible": True,
                "actions": [
                    {"tool_name": "browser_navigate", "arguments": {"url": LOCAL_TEST_URL}}
                ]
            }

            step_responses = [
                # After navigate observation, read page
                {
                    "is_complete": False,
                    "reasoning": "Page navigated. Now read page structure.",
                    "action": {"tool_name": "browser_read", "arguments": {}}
                },
                # After reading, observe username input and type
                {
                    "is_complete": False,
                    "reasoning": "Observed username input field. Type username.",
                    "action": {"tool_name": "browser_type", "arguments": {"selector": "#username", "text": "adaptive_user"}}
                },
                # After typing, click the action button
                {
                    "is_complete": False,
                    "reasoning": "Username filled. Click action button to submit.",
                    "action": {"tool_name": "browser_click", "arguments": {"selector": "#action-btn"}}
                },
                # Declare complete
                {
                    "is_complete": True,
                    "completion_summary": "All actions successfully executed adaptively.",
                    "action": None
                }
            ]

            mock_llm = SequenceMockLLM(initial_plan, step_responses)
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)
            runtime = AgentRuntime(llm_provider=mock_llm, tool_registry=registry, planner=planner)

            task = Task(user_goal="Interact with local form adaptively")
            result_task = await runtime.execute_task(task)

            try:
                self.assertEqual(result_task.status, TaskStatus.COMPLETED)
                self.assertEqual(runtime.state, AgentState.COMPLETED)

                # Verify all steps executed in order
                tools_run = [a.tool_name for a in runtime.executed_actions]
                self.assertEqual(tools_run, ["browser_navigate", "browser_read", "browser_type", "browser_click"])

                # Verify each step produced an observation
                self.assertEqual(len(runtime.observations), 4)
                for obs in runtime.observations:
                    self.assertTrue(obs.success)

                # Verify final completion summary recorded
                self.assertIn("completion_summary", result_task.metadata)
            finally:
                await session.close()

        asyncio.run(run_test())

    def test_failure_followed_by_changed_action(self):
        """Test B: Failure followed by changed action:
        Attempt save -> validation error -> observe failure -> planner changes action to supply missing data -> save again -> success.
        """
        async def run_test():
            registry = ToolRegistry()
            validation_tool = DummyValidationFailingTool()
            registry.register(validation_tool)

            initial_plan = {
                "goal": "Save invoice",
                "is_feasible": True,
                "actions": [
                    {"tool_name": "save_invoice_tool", "arguments": {"due_date_present": False}}
                ]
            }

            step_responses = [
                # In response to the validation error in observation, planner adapts by providing due_date_present=True
                {
                    "is_complete": False,
                    "reasoning": "Previous save failed because due_date was missing. Providing due_date now.",
                    "action": {"tool_name": "save_invoice_tool", "arguments": {"due_date_present": True}}
                },
                # After successful save, declare complete
                {
                    "is_complete": True,
                    "completion_summary": "Invoice saved with required due date.",
                    "action": None
                }
            ]

            mock_llm = SequenceMockLLM(initial_plan, step_responses)
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)
            runtime = AgentRuntime(llm_provider=mock_llm, tool_registry=registry, planner=planner)

            task = Task(user_goal="Save invoice with validation")
            result_task = await runtime.execute_task(task)

            self.assertEqual(result_task.status, TaskStatus.COMPLETED)
            self.assertEqual(runtime.state, AgentState.COMPLETED)

            # Check that two actions were executed
            self.assertEqual(len(runtime.executed_actions), 2)
            self.assertFalse(runtime.observations[0].success)
            self.assertIn("Validation error", runtime.observations[0].error)

            # Second action succeeded
            self.assertTrue(runtime.observations[1].success)
            self.assertEqual(runtime.executed_actions[1].arguments, {"due_date_present": True})

            # Verify that the LLM received the failure and recovery context in prompt
            second_prompt = mock_llm.prompts_received[1]
            self.assertIn("Validation error", second_prompt)
            self.assertIn("Policy: CORRECT_DATA", second_prompt)

        asyncio.run(run_test())

    def test_repeated_failure_reaches_bounded_termination(self):
        """Test C: Repeated failure reaches bounded termination without infinite loops."""
        async def run_test():
            registry = ToolRegistry()
            failing_tool = DummyPersistentFailingTool()
            registry.register(failing_tool)

            initial_plan = {
                "goal": "Test failing tool bounded termination",
                "is_feasible": True,
                "actions": [
                    {"tool_name": "persistent_failing_tool", "arguments": {}}
                ]
            }

            # Continuous retries
            step_responses = [
                {
                    "is_complete": False,
                    "reasoning": f"Retry attempt {i}",
                    "action": {"tool_name": "persistent_failing_tool", "arguments": {"retry": i}}
                }
                for i in range(1, 10)
            ]

            mock_llm = SequenceMockLLM(initial_plan, step_responses)
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)
            # Set a tight step budget of 4
            runtime = AgentRuntime(
                llm_provider=mock_llm,
                tool_registry=registry,
                planner=planner,
                max_dynamic_steps=4
            )

            task = Task(user_goal="Execute bounded failing task")
            result_task = await runtime.execute_task(task)

            # Must terminate and not exceed budget
            self.assertEqual(result_task.status, TaskStatus.FAILED)
            self.assertEqual(runtime.state, AgentState.FAILED)
            self.assertLessEqual(len(runtime.executed_actions), 4)
            self.assertTrue(result_task.metadata.get("error"))

        asyncio.run(run_test())

    def test_step_budget_exhaustion(self):
        """Test that exceeding the max_dynamic_steps budget halts execution with an exhaustion error."""
        async def run_test():
            registry = ToolRegistry()

            class DummySuccessTool(Tool):
                @property
                def name(self) -> str:
                    return "dummy_noop_tool"
                @property
                def description(self) -> str:
                    return "Always succeeds."
                @property
                def input_schema(self) -> Dict[str, Any]:
                    return {"type": "object"}
                async def execute(self, **kwargs: Any) -> Observation:
                    return Observation(action_id="noop", success=True, result={"ok": True})

            registry.register(DummySuccessTool())

            initial_plan = {
                "goal": "Test step budget exhaustion",
                "is_feasible": True,
                "actions": [{"tool_name": "dummy_noop_tool", "arguments": {}}]
            }

            step_responses = [
                {
                    "is_complete": False,
                    "reasoning": f"Keep going step {i}",
                    "action": {"tool_name": "dummy_noop_tool", "arguments": {"step": i}}
                }
                for i in range(1, 10)
            ]

            mock_llm = SequenceMockLLM(initial_plan, step_responses)
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)
            runtime = AgentRuntime(
                llm_provider=mock_llm,
                tool_registry=registry,
                planner=planner,
                max_dynamic_steps=3
            )

            task = Task(user_goal="Loop indefinitely until budget exhausted")
            result_task = await runtime.execute_task(task)

            self.assertEqual(result_task.status, TaskStatus.FAILED)
            self.assertEqual(runtime.state, AgentState.FAILED)
            self.assertLessEqual(len(runtime.executed_actions), 3)
            self.assertIn("exhausted", result_task.metadata.get("error", "").lower())

        asyncio.run(run_test())

    def test_duplicate_action_loop_protection(self):
        """Test that attempting the exact same failed action repeatedly is blocked."""
        async def run_test():
            registry = ToolRegistry()
            failing_tool = DummyPersistentFailingTool()
            registry.register(failing_tool)

            initial_plan = {
                "goal": "Test duplicate action loop protection",
                "is_feasible": True,
                "actions": [
                    {"tool_name": "persistent_failing_tool", "arguments": {}}
                ]
            }

            # Planner unhelpfully tries repeating the exact same failed action
            step_responses = [
                {
                    "is_complete": False,
                    "reasoning": "Try again with same arguments",
                    "action": {"tool_name": "persistent_failing_tool", "arguments": {}}
                },
                {
                    "is_complete": False,
                    "reasoning": "Try yet again with same arguments",
                    "action": {"tool_name": "persistent_failing_tool", "arguments": {}}
                }
            ]

            mock_llm = SequenceMockLLM(initial_plan, step_responses)
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)
            runtime = AgentRuntime(llm_provider=mock_llm, tool_registry=registry, planner=planner)

            task = Task(user_goal="Test duplicate action prevention")
            result_task = await runtime.execute_task(task)

            self.assertEqual(result_task.status, TaskStatus.FAILED)
            self.assertEqual(runtime.state, AgentState.FAILED)
            self.assertIn("loop detected", result_task.metadata.get("error", "").lower())

        asyncio.run(run_test())

    def test_planner_cannot_select_unavailable_tool(self):
        """Test D: Planner cannot select an unavailable tool."""
        async def run_test():
            registry = ToolRegistry()
            # Register only one known tool
            registry.register(DummyPersistentFailingTool())

            mock_llm = SequenceMockLLM(
                initial_plan={
                    "goal": "Test unavailable tool",
                    "is_feasible": True,
                    "actions": [{"tool_name": "persistent_failing_tool", "arguments": {}}]
                },
                step_responses=[
                    {
                        "is_complete": False,
                        "reasoning": "Attempting to use hallucinated tool",
                        "action": {"tool_name": "unregistered_database_delete", "arguments": {}}
                    }
                ]
            )
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)

            task = Task(user_goal="Attempt unavailable tool selection")
            decision = await planner.decide_next_action(
                task=task,
                action_history=[],
                observations=[],
            )

            # Must reject tool and set action to None
            self.assertIsNone(decision.action)
            self.assertIn("not registered in ToolRegistry", decision.reasoning)

        asyncio.run(run_test())

    def test_human_intervention_decision(self):
        """Test that when planner decides human intervention is needed, runtime transitions to NEEDS_HUMAN."""
        async def run_test():
            registry = ToolRegistry()
            registry.register(DummyPersistentFailingTool())

            initial_plan = {
                "goal": "Process restricted transaction",
                "is_feasible": True,
                "actions": [
                    {"tool_name": "persistent_failing_tool", "arguments": {}}
                ]
            }

            step_responses = [
                {
                    "is_complete": False,
                    "needs_human": True,
                    "reasoning": "Action requires executive sign-off and two-factor approval.",
                    "action": None
                }
            ]

            mock_llm = SequenceMockLLM(initial_plan, step_responses)
            planner = Planner(llm_provider=mock_llm, tool_registry=registry)
            runtime = AgentRuntime(llm_provider=mock_llm, tool_registry=registry, planner=planner)

            task = Task(user_goal="Restricted transaction")
            result_task = await runtime.execute_task(task)

            self.assertEqual(result_task.status, TaskStatus.NEEDS_HUMAN)
            self.assertEqual(runtime.state, AgentState.NEEDS_HUMAN)
            self.assertIn("sign-off", result_task.metadata.get("human_intervention_reason", ""))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
