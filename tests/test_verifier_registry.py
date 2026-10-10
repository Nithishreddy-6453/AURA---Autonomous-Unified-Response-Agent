import json
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.task import Task, TaskStatus
from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry
from backend.verification.finance_verifier import FinanceInvoiceVerifier
from backend.verification.registry import VerifierRegistry, get_default_verifier_registry
from backend.verification.verifier import BaseVerifier, VerificationResult


class DummyMockLLM(LLMProvider):
    """Predictable mock LLM returning configured initial plan and dynamic step responses."""

    def __init__(
        self,
        responses: Optional[List[Dict[str, Any]]] = None,
        initial_plan: Optional[Dict[str, Any]] = None,
    ):
        self.initial_plan = initial_plan or {
            "goal": "Test goal",
            "steps": ["Step 1"],
            "actions": [{"tool_name": "echo_tool", "arguments": {"msg": "hello"}}],
        }
        self.responses = list(responses or [])
        self.step_index = 0

    async def generate(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps(self.initial_plan)

        if self.step_index < len(self.responses):
            resp = self.responses[self.step_index]
            self.step_index += 1
            return json.dumps(resp)
        return json.dumps({
            "is_complete": True,
            "completion_summary": "Done.",
            "action": None,
        })

    async def chat(self, messages: list, temperature: float = 0.0, **kwargs: Any) -> str:
        return await self.generate(messages[-1]["content"] if messages else "")


from backend.models.observation import Observation
from backend.policy.risk import ActionRisk


class MockEchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Echo tool"

    @property
    def risk_level(self) -> ActionRisk:
        return ActionRisk.READ

    @property
    def capabilities(self) -> List[str]:
        return ["read"]

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"msg": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> Observation:
        return Observation(action_id=kwargs.get("action_id", ""), success=True, result={"echo": kwargs.get("msg")})



class DummyCustomVerifier(BaseVerifier):
    source_name: str = "custom_verifier"

    def __init__(self, can_verify_result: bool = True, verify_result: Optional[VerificationResult] = None):
        self._can_verify = can_verify_result
        self._verify_result = verify_result or VerificationResult(True, "Custom verified")
        self.verify_called = False

    def can_verify(self, task: Task) -> bool:
        return self._can_verify

    async def verify(self, task_metadata: Dict[str, Any], source_reference: Any = None) -> VerificationResult:
        self.verify_called = True
        return self._verify_result


class MinimalBaseVerifier(BaseVerifier):
    async def verify(self, task_metadata: Dict[str, Any], extracted_data: Dict[str, Any]) -> VerificationResult:
        return VerificationResult(True, "Minimal verified")


class TestVerifierRegistry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(MockEchoTool())

    def test_base_verifier_default_can_verify(self):
        """BaseVerifier.can_verify must return False by default."""
        verifier = MinimalBaseVerifier()
        task = Task(user_goal="Test arbitrary goal")
        self.assertFalse(verifier.can_verify(task))

    def test_finance_verifier_can_verify_goal_matching(self):
        """FinanceInvoiceVerifier should match goals mentioning both invoice and finance."""
        verifier = FinanceInvoiceVerifier()

        # Matches when both 'invoice' and 'finance' are present
        task1 = Task(user_goal="Enter new invoice into the finance portal")
        self.assertTrue(verifier.can_verify(task1))

        # Case-insensitive matching
        task2 = Task(user_goal="INVOICE processing in FINANCE department")
        self.assertTrue(verifier.can_verify(task2))

        # Does not match if only one keyword is present
        task3 = Task(user_goal="Check invoice status on customer page")
        self.assertFalse(verifier.can_verify(task3))

        task4 = Task(user_goal="Review finance report")
        self.assertFalse(verifier.can_verify(task4))

        # Does not match unrelated goals
        task5 = Task(user_goal="Search employee onboarding documents")
        self.assertFalse(verifier.can_verify(task5))

        # None task returns False
        self.assertFalse(verifier.can_verify(None))  # type: ignore

    def test_finance_verifier_can_verify_metadata_source_references(self):
        """FinanceInvoiceVerifier should match tasks with explicit source references."""
        verifier = FinanceInvoiceVerifier()

        # source_document in metadata
        task1 = Task(user_goal="General doc entry", metadata={"source_document": "data/doc.txt"})
        self.assertTrue(verifier.can_verify(task1))

        # source_file in metadata
        task2 = Task(user_goal="General doc entry", metadata={"source_file": "data/doc.txt"})
        self.assertTrue(verifier.can_verify(task2))

        # source_reference in metadata
        task3 = Task(user_goal="General doc entry", metadata={"source_reference": "data/doc.txt"})
        self.assertTrue(verifier.can_verify(task3))

        # source_ref in metadata
        task4 = Task(user_goal="General doc entry", metadata={"source_ref": "data/doc.txt"})
        self.assertTrue(verifier.can_verify(task4))

    def test_source_ref_task_without_finance_keywords_matches_existing_behavior(self):
        """Preserves existing baseline dispatch: if source_ref is set, finance verification triggers

        even if user_goal does not mention finance or invoice.
        """
        verifier = FinanceInvoiceVerifier()
        task = Task(user_goal="Archive document to records", metadata={"source_document": "archive_file.txt"})
        self.assertTrue(verifier.can_verify(task))

    def test_registry_registration_and_selection(self):
        """VerifierRegistry should select the first matching verifier."""
        registry = VerifierRegistry()
        verifier1 = DummyCustomVerifier(can_verify_result=False)
        verifier2 = DummyCustomVerifier(can_verify_result=True)

        registry.register(verifier1)
        registry.register(verifier2)

        task = Task(user_goal="Process document")
        selected = registry.get_verifier(task)
        self.assertIs(selected, verifier2)

    def test_registry_returns_none_when_no_verifier_matches(self):
        """VerifierRegistry returns None when no registered verifier can handle the task."""
        registry = VerifierRegistry()
        verifier1 = DummyCustomVerifier(can_verify_result=False)
        registry.register(verifier1)

        task = Task(user_goal="Unmatched task")
        self.assertIsNone(registry.get_verifier(task))

    def test_registry_deterministic_first_match_order(self):
        """VerifierRegistry evaluates in registration order and returns first match deterministically."""
        registry = VerifierRegistry()
        verifier_first = DummyCustomVerifier(can_verify_result=True)
        verifier_second = DummyCustomVerifier(can_verify_result=True)

        registry.register(verifier_first)
        registry.register(verifier_second)

        task = Task(user_goal="Any task")
        self.assertIs(registry.get_verifier(task), verifier_first)

    def test_default_verifier_registry(self):
        """get_default_verifier_registry contains FinanceInvoiceVerifier."""
        registry = get_default_verifier_registry()
        self.assertEqual(len(registry.verifiers), 1)
        self.assertIsInstance(registry.verifiers[0], FinanceInvoiceVerifier)

    async def test_runtime_uses_injected_registry(self):
        """AgentRuntime uses an injected VerifierRegistry during task completion."""
        custom_verifier = DummyCustomVerifier(can_verify_result=True)
        registry = VerifierRegistry([custom_verifier])

        llm = DummyMockLLM(
            responses=[
                {
                    "is_complete": True,
                    "completion_summary": "Custom task completed successfully",
                    "action": None,
                }
            ]
        )

        runtime = AgentRuntime(
            llm_provider=llm,
            tool_registry=self.registry,
            verifier_registry=registry,
        )

        task = Task(user_goal="Custom domain task")
        result = await runtime.execute_task(task, use_dynamic_adaptation=True)

        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertTrue(custom_verifier.verify_called)

    async def test_default_runtime_retains_finance_verification(self):
        """Default AgentRuntime triggers FinanceInvoiceVerifier for invoice/finance tasks."""
        llm = DummyMockLLM(
            responses=[
                {
                    "is_complete": True,
                    "completion_summary": "Invoice completed",
                    "action": None,
                }
            ]
        )

        runtime = AgentRuntime(
            llm_provider=llm,
            tool_registry=self.registry,
        )

        # Mock the registered FinanceInvoiceVerifier.verify
        matched_verifier = runtime.verifier_registry.verifiers[0]
        self.assertIsInstance(matched_verifier, FinanceInvoiceVerifier)

        with patch.object(matched_verifier, "verify", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = VerificationResult(True, "Finance verified")

            task = Task(user_goal="Enter invoice into finance portal")
            result = await runtime.execute_task(task, use_dynamic_adaptation=True)

            self.assertEqual(result.status, TaskStatus.COMPLETED)
            mock_verify.assert_awaited_once()

    async def test_runtime_non_matching_task_completes_without_verifier(self):
        """A task without matching verifier completes normally when planner says is_complete."""
        llm = DummyMockLLM(
            responses=[
                {
                    "is_complete": True,
                    "completion_summary": "General task completed",
                    "action": None,
                }
            ]
        )

        runtime = AgentRuntime(
            llm_provider=llm,
            tool_registry=self.registry,
        )

        task = Task(user_goal="Search list of employee names in company records")
        result = await runtime.execute_task(task, use_dynamic_adaptation=True)

        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(runtime.state, AgentState.COMPLETED)

    async def test_finance_verifier_property_compatibility(self):
        """Assigning runtime.finance_verifier preserves backwards compatibility with legacy tests."""
        llm = DummyMockLLM(
            responses=[
                {
                    "is_complete": True,
                    "completion_summary": "Done",
                    "action": None,
                }
            ]
        )

        runtime = AgentRuntime(
            llm_provider=llm,
            tool_registry=self.registry,
        )

        custom_verifier = DummyCustomVerifier(can_verify_result=True)
        # Direct assignment to legacy property
        runtime.finance_verifier = custom_verifier

        self.assertIs(runtime.finance_verifier, custom_verifier)

        task = Task(user_goal="Enter invoice into finance portal")
        result = await runtime.execute_task(task, use_dynamic_adaptation=True)

        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertTrue(custom_verifier.verify_called)

    def test_finance_verifier_getter_does_not_expose_unrelated_verifier(self):
        """A registry without a Finance verifier must not expose an unrelated verifier through runtime.finance_verifier."""
        unrelated_verifier = DummyCustomVerifier(can_verify_result=True)
        unrelated_verifier.source_name = "hr_verifier"
        registry = VerifierRegistry([unrelated_verifier])

        runtime = AgentRuntime(
            verifier_registry=registry,
            tool_registry=self.registry,
        )

        # Must be None, NOT unrelated_verifier
        self.assertIsNone(runtime.finance_verifier)

    def test_finance_verifier_getter_returns_none_on_empty_registry(self):
        """Injected empty registry returns None for runtime.finance_verifier."""
        empty_registry = VerifierRegistry([])
        runtime = AgentRuntime(
            verifier_registry=empty_registry,
            tool_registry=self.registry,
        )
        self.assertIsNone(runtime.finance_verifier)

    def test_injected_empty_registry_preserved(self):
        """Injected empty registry is preserved via explicit None check, not replaced by default."""
        empty_registry = VerifierRegistry([])
        runtime = AgentRuntime(
            verifier_registry=empty_registry,
            tool_registry=self.registry,
        )
        self.assertEqual(len(runtime.verifier_registry), 0)
        self.assertIs(runtime.verifier_registry, empty_registry)

    def test_replacing_finance_verifier_preserves_unrelated_registered_verifiers(self):
        """Replacing the Finance verifier through legacy setter must preserve unrelated registered verifiers."""
        hr_verifier = DummyCustomVerifier(can_verify_result=False)
        hr_verifier.source_name = "hr_verifier"

        crm_verifier = DummyCustomVerifier(can_verify_result=False)
        crm_verifier.source_name = "crm_verifier"

        original_finance = FinanceInvoiceVerifier()
        registry = VerifierRegistry([hr_verifier, original_finance, crm_verifier])

        runtime = AgentRuntime(
            verifier_registry=registry,
            tool_registry=self.registry,
        )

        new_finance_verifier = DummyCustomVerifier(can_verify_result=True)
        runtime.finance_verifier = new_finance_verifier

        # Verifier count must remain 3
        self.assertEqual(len(runtime.verifier_registry), 3)
        # Order and instances of unrelated verifiers must be preserved
        self.assertIs(runtime.verifier_registry.verifiers[0], hr_verifier)
        self.assertIs(runtime.verifier_registry.verifiers[2], crm_verifier)
        # The finance slot contains the new finance verifier (or adapter wrapping it)
        slot_verifier = runtime.verifier_registry.verifiers[1]
        self.assertIs(getattr(slot_verifier, "wrapped", slot_verifier), new_finance_verifier)
        # Getter returns the new finance verifier
        self.assertIs(runtime.finance_verifier, new_finance_verifier)


    async def test_legacy_verifier_double_uses_adapter_without_monkey_patching(self):
        """Legacy verifiers without can_verify are wrapped in an adapter without mutating the double."""
        class RawLegacyDouble:
            def __init__(self):
                self.called = False

            async def verify(self, metadata, source_ref=None):
                self.called = True
                return VerificationResult(True, "Double verified")

        raw_double = RawLegacyDouble()
        self.assertFalse(hasattr(raw_double, "can_verify"))

        llm = DummyMockLLM(
            responses=[
                {
                    "is_complete": True,
                    "completion_summary": "Invoice processed",
                    "action": None,
                }
            ]
        )

        runtime = AgentRuntime(
            llm_provider=llm,
            tool_registry=self.registry,
        )

        # Set raw double without can_verify
        runtime.finance_verifier = raw_double

        # Verify the raw double was NOT monkey-patched
        self.assertFalse(hasattr(raw_double, "can_verify"))

        # Getter returns the underlying double
        self.assertIs(runtime.finance_verifier, raw_double)

        # Execution triggers verification via the adapter
        task = Task(user_goal="Enter invoice into finance portal")
        result = await runtime.execute_task(task, use_dynamic_adaptation=True)

        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertTrue(raw_double.called)


if __name__ == "__main__":
    unittest.main()

