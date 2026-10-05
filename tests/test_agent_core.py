import asyncio
import json
import unittest
from typing import Any, Dict

from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.schemas import PlanActionSchema, PlanResponseSchema, PlanningResult
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus
from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Test Doubles
# ---------------------------------------------------------------------------

class MockLLMProvider(LLMProvider):
    """Test double for LLM provider returning programmed responses."""

    def __init__(self, response_text: str = "") -> None:
        self.response_text = response_text
        self.last_prompt = ""
        self.last_system_instruction = ""

    async def generate(
        self,
        prompt: str,
        system_instruction: str = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return self.response_text

    async def chat(
        self,
        messages: list,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        return self.response_text


class DummyEchoTool(Tool):
    """A simple dummy tool for testing registration and execution."""

    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Echoes back input payload for testing."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> Observation:
        return Observation(
            action_id=kwargs.get("action_id", "test-act"),
            success=True,
            result={"echo": kwargs.get("message", "")},
        )


class FailingTool(Tool):
    """Dummy tool that returns a failed observation."""

    @property
    def name(self) -> str:
        return "failing_tool"

    @property
    def description(self) -> str:
        return "Always fails for testing error handling."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object"}

    async def execute(self, **kwargs: Any) -> Observation:
        return Observation(
            action_id=kwargs.get("action_id", "test-act"),
            success=False,
            error="Deliberate tool failure.",
        )


# ---------------------------------------------------------------------------
# Unit Test Cases
# ---------------------------------------------------------------------------

class TestAuraAgentCore(unittest.TestCase):

    def test_task_creation(self):
        """Test task model creation, defaults, and status."""
        task = Task(user_goal="Process invoice #1234")
        self.assertTrue(task.task_id)
        self.assertEqual(task.user_goal, "Process invoice #1234")
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIsNotNone(task.created_at)
        self.assertEqual(task.metadata, {})

    def test_action_validation(self):
        """Test action model validation and status defaults."""
        action = Action(tool_name="search_invoice", arguments={"id": "123"})
        self.assertTrue(action.action_id)
        self.assertEqual(action.tool_name, "search_invoice")
        self.assertEqual(action.arguments, {"id": "123"})
        self.assertEqual(action.status, ActionStatus.PENDING)
        self.assertEqual(action.retry_count, 0)

    def test_plan_validation(self):
        """Test plan model and structured actions list."""
        action1 = Action(tool_name="tool_a", arguments={"arg1": 10})
        action2 = Action(tool_name="tool_b", arguments={"arg2": "val"})
        plan = Plan(task_id="task-1", goal="Test Goal", actions=[action1, action2])

        self.assertTrue(plan.plan_id)
        self.assertEqual(plan.task_id, "task-1")
        self.assertEqual(len(plan.actions), 2)
        self.assertEqual(plan.actions[0].tool_name, "tool_a")

    def test_observation_model(self):
        """Test observation model captures success, result, and errors."""
        obs = Observation(action_id="act-1", success=True, result={"amount": 450.0})
        self.assertEqual(obs.action_id, "act-1")
        self.assertTrue(obs.success)
        self.assertEqual(obs.result, {"amount": 450.0})
        self.assertIsNone(obs.error)

    def test_tool_registration_and_lookup(self):
        """Test registering, checking, listing, and retrieving tools."""
        registry = ToolRegistry()
        tool = DummyEchoTool()

        self.assertFalse(registry.has("echo_tool"))
        registry.register(tool)
        self.assertTrue(registry.has("echo_tool"))
        self.assertEqual(registry.get("echo_tool"), tool)
        self.assertEqual(len(registry.list_tools()), 1)

    def test_unknown_tool_rejection(self):
        """Test that unknown tool retrieval raises KeyError."""
        registry = ToolRegistry()
        with self.assertRaises(KeyError):
            registry.get("non_existent_tool")

    def test_planner_rejecting_unavailable_tools(self):
        """Test that planner rejects plans containing unlisted/hallucinated tools."""
        registry = ToolRegistry()
        registry.register(DummyEchoTool())

        # Mock LLM returns a hallucinated tool name 'browse_web'
        hallucinated_plan_json = json.dumps({
            "goal": "Browse the web",
            "is_feasible": True,
            "actions": [
                {"tool_name": "browse_web", "arguments": {"url": "https://example.com"}}
            ],
        })

        mock_llm = MockLLMProvider(response_text=hallucinated_plan_json)
        planner = Planner(llm_provider=mock_llm, tool_registry=registry)

        task = Task(user_goal="Browse website")
        result = asyncio.run(planner.create_plan(task))

        self.assertFalse(result.success)
        self.assertIn("unavailable tool 'browse_web'", result.error)

    def test_planner_infeasible_reporting(self):
        """Test that planner handles tasks requiring unavailable capabilities."""
        registry = ToolRegistry()
        mock_response = json.dumps({
            "goal": "Fly a rocket",
            "is_feasible": False,
            "unsupported_reason": "No space flight tools registered.",
            "actions": [],
        })
        mock_llm = MockLLMProvider(response_text=mock_response)
        planner = Planner(llm_provider=mock_llm, tool_registry=registry)

        task = Task(user_goal="Launch satellite")
        result = asyncio.run(planner.create_plan(task))

        self.assertFalse(result.success)
        self.assertIn("infeasible with available tools", result.error)

    def test_runtime_initialization(self):
        """Test AgentRuntime initialization with defaults."""
        mock_llm = MockLLMProvider()
        runtime = AgentRuntime(llm_provider=mock_llm)
        self.assertEqual(runtime.state, AgentState.RECEIVED)
        self.assertIsNone(runtime.current_task)
        self.assertIsNone(runtime.current_plan)

    def test_state_transitions_success_flow(self):
        """Test full runtime state lifecycle on successful task run."""
        registry = ToolRegistry()
        registry.register(DummyEchoTool())

        valid_plan_json = json.dumps({
            "goal": "Echo test message",
            "is_feasible": True,
            "actions": [
                {"tool_name": "echo_tool", "arguments": {"message": "Hello AURA"}}
            ],
        })

        mock_llm = MockLLMProvider(response_text=valid_plan_json)
        state_history = []

        def record_state(new_state: AgentState, t: Task):
            state_history.append(new_state)

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=registry,
            on_state_change=record_state,
        )

        task = Task(user_goal="Say hello")
        completed_task = asyncio.run(runtime.execute_task(task))

        self.assertEqual(completed_task.status, TaskStatus.COMPLETED)
        self.assertEqual(runtime.state, AgentState.COMPLETED)

        # Expected transition sequence:
        expected_sequence = [
            AgentState.RECEIVED,
            AgentState.UNDERSTANDING,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.OBSERVING,
            AgentState.VERIFYING,
            AgentState.COMPLETED,
        ]
        self.assertEqual(state_history, expected_sequence)
        self.assertEqual(len(runtime.observations), 1)
        self.assertTrue(runtime.observations[0].success)

    def test_state_transitions_tool_failure_flow(self):
        """Test runtime state lifecycle when a tool execution fails."""
        registry = ToolRegistry()
        registry.register(FailingTool())

        plan_json = json.dumps({
            "goal": "Execute failing task",
            "is_feasible": True,
            "actions": [{"tool_name": "failing_tool", "arguments": {}}],
        })

        mock_llm = MockLLMProvider(response_text=plan_json)
        state_history = []

        def record_state(new_state: AgentState, t: Task):
            state_history.append(new_state)

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=registry,
            on_state_change=record_state,
        )

        task = Task(user_goal="Run failing tool")
        failed_task = asyncio.run(runtime.execute_task(task))

        self.assertEqual(failed_task.status, TaskStatus.FAILED)
        self.assertEqual(runtime.state, AgentState.FAILED)
        self.assertIn(AgentState.ADAPTING, state_history)
        self.assertIn(AgentState.FAILED, state_history)


if __name__ == "__main__":
    unittest.main()
