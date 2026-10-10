import json
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

from backend.agent.planner import (
    DEFAULT_FINANCE_GUIDELINES,
    GENERIC_NEXT_ACTION_SYSTEM_PROMPT,
    GENERIC_PLANNER_SYSTEM_PROMPT,
    Planner,
)
from backend.agent.runtime import AgentRuntime
from backend.agent.schemas import NextActionResponseSchema, PlanActionSchema, PlanningResult
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry


class RecordingMockLLM(LLMProvider):
    """Mock LLM that captures system_instruction and prompt and returns configured JSON."""

    def __init__(self, response_data: Optional[Dict[str, Any]] = None):
        self.last_prompt = ""
        self.last_system_instruction = ""
        self.response_data = response_data or {
            "goal": "Test goal",
            "is_feasible": True,
            "actions": [{"tool_name": "mock_tool", "arguments": {"arg": "val"}}],
        }

    async def generate(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return json.dumps(self.response_data)

    async def chat(self, messages: list, temperature: float = 0.0, **kwargs: Any) -> str:
        return ""


class SimpleMockTool(Tool):
    @property
    def name(self) -> str:
        return "mock_tool"

    @property
    def description(self) -> str:
        return "A mock tool for testing."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"arg": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> Observation:
        return Observation(action_id="1", success=True, result="Executed mock")


class TestPlannerGuidelines(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(SimpleMockTool())

    def test_generic_prompts_retain_essential_agent_instructions(self):
        """Generic prompts must contain core agent behavioral rules and no finance coupling."""
        # Generic Planner prompt rules
        self.assertIn("Available Tools", GENERIC_PLANNER_SYSTEM_PROMPT)
        self.assertIn("STRICT RULES:", GENERIC_PLANNER_SYSTEM_PROMPT)
        self.assertIn("is_feasible", GENERIC_PLANNER_SYSTEM_PROMPT)
        self.assertIn("raw JSON only", GENERIC_PLANNER_SYSTEM_PROMPT)

        # Must not contain domain-specific terms
        self.assertNotIn("invoice", GENERIC_PLANNER_SYSTEM_PROMPT.lower())
        self.assertNotIn("localhost:3000", GENERIC_PLANNER_SYSTEM_PROMPT)
        self.assertNotIn("save invoice", GENERIC_PLANNER_SYSTEM_PROMPT.lower())

        # Generic Next Action Reasoner prompt rules
        self.assertIn("is_complete", GENERIC_NEXT_ACTION_SYSTEM_PROMPT)
        self.assertIn("needs_human", GENERIC_NEXT_ACTION_SYSTEM_PROMPT)
        self.assertIn("Read source documents before using their contents", GENERIC_NEXT_ACTION_SYSTEM_PROMPT)
        self.assertIn("Verify or observe the outcome before declaring completion", GENERIC_NEXT_ACTION_SYSTEM_PROMPT)

        # Must not contain domain-specific terms
        self.assertNotIn("localhost:3000", GENERIC_NEXT_ACTION_SYSTEM_PROMPT)
        self.assertNotIn("invoice_id", GENERIC_NEXT_ACTION_SYSTEM_PROMPT)
        self.assertNotIn("save invoice", GENERIC_NEXT_ACTION_SYSTEM_PROMPT.lower())

    def test_default_planner_preserves_finance_guidelines(self):
        """Default Planner constructor (domain_guidelines=None) preserves existing Finance guidelines."""
        mock_llm = RecordingMockLLM()
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry)

        # Domain guidelines default to DEFAULT_FINANCE_GUIDELINES
        self.assertEqual(planner.domain_guidelines, DEFAULT_FINANCE_GUIDELINES)

        # Effective prompts contain domain guidelines and finance instructions
        effective_planner_prompt = planner.get_effective_planner_system_prompt()
        effective_next_prompt = planner.get_effective_next_action_system_prompt()

        self.assertIn("DOMAIN GUIDELINES:", effective_planner_prompt)
        self.assertIn("DOMAIN GUIDELINES:", effective_next_prompt)
        self.assertIn("http://localhost:3000/finance/invoices/new", effective_next_prompt)
        self.assertIn("invoice_id", effective_next_prompt)
        self.assertIn("Save Invoice", effective_next_prompt)

    def test_planner_with_empty_guidelines_excludes_finance_guidance(self):
        """Supplying domain_guidelines=[] excludes all domain guidelines and finance instructions."""
        mock_llm = RecordingMockLLM()
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry, domain_guidelines=[])

        self.assertEqual(planner.domain_guidelines, [])

        effective_planner_prompt = planner.get_effective_planner_system_prompt()
        effective_next_prompt = planner.get_effective_next_action_system_prompt()

        self.assertNotIn("DOMAIN GUIDELINES:", effective_planner_prompt)
        self.assertNotIn("DOMAIN GUIDELINES:", effective_next_prompt)
        self.assertNotIn("localhost:3000", effective_next_prompt)
        self.assertNotIn("invoice", effective_next_prompt.lower())

    def test_planner_with_custom_guidelines_includes_custom_and_excludes_finance(self):
        """Custom domain guidelines appear in effective prompts without finance coupling."""
        mock_llm = RecordingMockLLM()
        custom_rules = [
            "Navigate to http://hr.internal:8080/onboarding/new for employee records.",
            "Verify national identity number before submission.",
            "Click 'Complete Onboarding' button to finalize.",
        ]
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry, domain_guidelines=custom_rules)

        self.assertEqual(planner.domain_guidelines, custom_rules)

        effective_planner_prompt = planner.get_effective_planner_system_prompt()
        effective_next_prompt = planner.get_effective_next_action_system_prompt()

        # Custom rules present
        for rule in custom_rules:
            self.assertIn(rule, effective_planner_prompt)
            self.assertIn(rule, effective_next_prompt)

        # Finance rules excluded
        self.assertNotIn("localhost:3000", effective_planner_prompt)
        self.assertNotIn("localhost:3000", effective_next_prompt)
        self.assertNotIn("Save Invoice", effective_next_prompt)
        self.assertNotIn("invoice_id", effective_next_prompt)

    def test_guideline_normalization(self):
        """Whitespace and empty guidelines are safely sanitized during initialization."""
        mock_llm = RecordingMockLLM()
        raw_rules = ["  rule with leading/trailing spaces   ", "", "   ", "valid rule"]
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry, domain_guidelines=raw_rules)

        self.assertEqual(planner.domain_guidelines, ["rule with leading/trailing spaces", "valid rule"])

    async def test_initial_planning_uses_effective_guidelines(self):
        """create_plan passes the effective planner prompt with active guidelines to LLM."""
        mock_llm = RecordingMockLLM(
            response_data={
                "goal": "Test HR",
                "is_feasible": True,
                "actions": [{"tool_name": "mock_tool", "arguments": {"arg": "hr_data"}}],
            }
        )
        custom_rules = ["Always lookup employee record before updating."]
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry, domain_guidelines=custom_rules)

        task = Task(user_goal="Onboard employee")
        res = await planner.create_plan(task)

        self.assertTrue(res.success)
        self.assertIn("DOMAIN GUIDELINES:", mock_llm.last_system_instruction)
        self.assertIn("Always lookup employee record before updating.", mock_llm.last_system_instruction)
        self.assertNotIn("invoice", mock_llm.last_system_instruction.lower())

    async def test_adaptive_replanning_uses_effective_guidelines(self):
        """decide_next_action passes the effective next action prompt with active guidelines to LLM."""
        mock_llm = RecordingMockLLM(
            response_data={
                "is_complete": True,
                "completion_summary": "Task complete",
                "action": None,
            }
        )
        custom_rules = ["Take snapshot of completed badge."]
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry, domain_guidelines=custom_rules)

        task = Task(user_goal="Issue badge")
        decision = await planner.decide_next_action(
            task=task,
            action_history=[],
            observations=[],
        )

        self.assertTrue(decision.is_complete)
        self.assertIn("DOMAIN GUIDELINES:", mock_llm.last_system_instruction)
        self.assertIn("Take snapshot of completed badge.", mock_llm.last_system_instruction)
        self.assertNotIn("Save Invoice", mock_llm.last_system_instruction)

    def test_runtime_passes_domain_guidelines_to_planner(self):
        """AgentRuntime constructor forwards domain_guidelines to Planner."""
        mock_llm = RecordingMockLLM()
        custom_rules = ["Custom guideline for runtime"]
        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.registry,
            domain_guidelines=custom_rules,
        )

        self.assertEqual(runtime.planner.domain_guidelines, custom_rules)
        self.assertIn("Custom guideline for runtime", runtime.planner.get_effective_next_action_system_prompt())

    def test_default_runtime_preserves_default_finance_guidelines(self):
        """Default AgentRuntime constructor preserves DEFAULT_FINANCE_GUIDELINES in Planner."""
        mock_llm = RecordingMockLLM()
        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.registry,
        )

        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_FINANCE_GUIDELINES)
        self.assertIn("Save Invoice", runtime.planner.get_effective_next_action_system_prompt())

    async def test_structured_output_parsing_and_completion_unaffected(self):
        """Structured output parsing, completion decision, and human intervention remain fully intact."""
        # 1. Action decision
        mock_llm = RecordingMockLLM(
            response_data={
                "is_complete": False,
                "needs_human": False,
                "reasoning": "Need to invoke tool",
                "action": {"tool_name": "mock_tool", "arguments": {"arg": "test"}},
            }
        )
        planner = Planner(llm_provider=mock_llm, tool_registry=self.registry, domain_guidelines=[])
        task = Task(user_goal="Run step")
        decision = await planner.decide_next_action(task=task, action_history=[], observations=[])

        self.assertFalse(decision.is_complete)
        self.assertIsNotNone(decision.action)
        self.assertEqual(decision.action.tool_name, "mock_tool")
        self.assertEqual(decision.action.arguments, {"arg": "test"})

        # 2. Human intervention
        mock_llm.response_data = {
            "is_complete": False,
            "needs_human": True,
            "reasoning": "Need 2FA code",
            "action": None,
        }
        decision_human = await planner.decide_next_action(task=task, action_history=[], observations=[])
        self.assertTrue(decision_human.needs_human)
        self.assertEqual(decision_human.reasoning, "Need 2FA code")

        # 3. Completion
        mock_llm.response_data = {
            "is_complete": True,
            "needs_human": False,
            "completion_summary": "All steps executed",
            "action": None,
        }
        decision_complete = await planner.decide_next_action(task=task, action_history=[], observations=[])
        self.assertTrue(decision_complete.is_complete)
        self.assertEqual(decision_complete.completion_summary, "All steps executed")


if __name__ == "__main__":
    unittest.main()
