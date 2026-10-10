"""Regression test suite for AURA v0.5.0 stabilization and critical fixes.

Covers:
- Fix 1: False completion prevention on planner failure (explicit is_complete=True required)
- Fix 2: Exact action argument binding & single-use consumption in human approval
- Fix 3: Independent source-of-truth verification for Finance portal (break circularity)
- Fix 4: Browser navigation port configuration & validation
- Fix 5: CORS hardening & wildcard elimination
- Fix 6: Browser type JavaScript evaluation parameterization & safety
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.schemas import NextActionResponseSchema
from backend.agent.state import AgentState
from backend.api.main import app, get_allowed_origins
from backend.llm.base import LLMProvider
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.policy.decision import PolicyDecision
from backend.policy.engine import (
    ActionPolicy,
    DefaultActionPolicy,
    compute_action_fingerprint,
)
from backend.policy.risk import ActionRisk
from backend.tools.base import Tool
from backend.tools.browser.browser_navigate import (
    DEFAULT_ALLOWED_PORTS,
    BrowserNavigateTool,
    get_allowed_ports,
)
from backend.tools.browser.browser_session import BrowserSession
from backend.tools.browser.browser_type import BrowserTypeTool
from backend.tools.registry import ToolRegistry
from backend.verification.finance_verifier import (
    FinanceInvoiceVerifier,
    parse_source_document,
)


class DummyMockLLM(LLMProvider):
    """Predictable mock LLM returning configured responses."""

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


class MockPaymentTool(Tool):
    @property
    def name(self) -> str:
        return "authorize_invoice_payment"

    @property
    def description(self) -> str:
        return "Financial payment authorization tool"

    @property
    def risk_level(self) -> ActionRisk:
        return ActionRisk.FINANCIAL

    @property
    def capabilities(self) -> List[str]:
        return ["financial"]

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string"},
                "amount": {"type": "number"},
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        return Observation(
            action_id=kwargs.get("action_id", ""),
            success=True,
            result={"status": "paid", "amount": kwargs.get("amount")},
        )


class TestStabilizationFix1PlannerCompletion(unittest.IsolatedAsyncioTestCase):
    """FIX #1 Regression tests: Runtime must never falsely complete after planner failure."""

    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_memory.db"
        self.memory = SQLiteMemoryStore(db_path=self.db_path)

        self.registry = ToolRegistry()
        self.registry.register(MockEchoTool())

    async def asyncTearDown(self):
        self.tmp_dir.cleanup()

    async def test_planner_returns_action_none_unexpectedly_does_not_complete(self):
        """A. Planner returns action=None unexpectedly -> task does NOT become COMPLETED."""
        # LLM returns action=None and is_complete=False
        llm = DummyMockLLM([
            {"is_complete": False, "reasoning": "I have no idea what to do next", "action": None},
            {"is_complete": False, "reasoning": "Still no action", "action": None},
            {"is_complete": False, "reasoning": "Still no action", "action": None},
        ])
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            llm_provider=llm,
            max_dynamic_steps=3,
        )

        task = Task(user_goal="Process invoice with failing planner")
        res = await runtime.execute_task(task)

        self.assertNotEqual(res.status, TaskStatus.COMPLETED)
        self.assertEqual(res.status, TaskStatus.FAILED)
        self.assertEqual(runtime.state, AgentState.FAILED)

    async def test_planner_llm_exception_transitions_to_failed(self):
        """B. Planner/LLM exception -> task becomes FAILED."""
        broken_llm = MagicMock(spec=LLMProvider)
        broken_llm.generate = AsyncMock(side_effect=RuntimeError("LLM API connection timeout 503"))

        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            llm_provider=broken_llm,
            max_dynamic_steps=2,
        )

        task = Task(user_goal="Process invoice with crashing LLM")
        res = await runtime.execute_task(task)

        self.assertNotEqual(res.status, TaskStatus.COMPLETED)
        self.assertEqual(res.status, TaskStatus.FAILED)
        self.assertEqual(runtime.state, AgentState.FAILED)

    async def test_unregistered_tool_response_does_not_complete(self):
        """C. Unregistered tool proposal -> task does not become COMPLETED."""
        llm = DummyMockLLM([
            {
                "is_complete": False,
                "reasoning": "Attempting invalid tool call",
                "action": {"tool_name": "non_existent_tool", "arguments": {"x": 1}},
            },
            {
                "is_complete": False,
                "reasoning": "Attempting again",
                "action": {"tool_name": "non_existent_tool", "arguments": {"x": 1}},
            },
        ])
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            llm_provider=llm,
            max_dynamic_steps=2,
        )

        task = Task(user_goal="Do work with bad tool")
        res = await runtime.execute_task(task)

        self.assertNotEqual(res.status, TaskStatus.COMPLETED)
        self.assertEqual(res.status, TaskStatus.FAILED)

    async def test_explicit_is_complete_triggers_verifying_and_completes(self):
        """D. Explicit is_complete=True -> verification flow applies and task completes."""
        llm = DummyMockLLM([
            {
                "is_complete": False,
                "reasoning": "Echoing message first",
                "action": {"tool_name": "echo_tool", "arguments": {"msg": "hello"}},
            },
            {
                "is_complete": True,
                "completion_summary": "Task finished successfully.",
                "action": None,
            },
        ])
        state_history = []
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            llm_provider=llm,
            on_state_change=lambda s, t: state_history.append(s),
            max_dynamic_steps=5,
        )

        task = Task(user_goal="Say hello cleanly")
        res = await runtime.execute_task(task)

        self.assertEqual(res.status, TaskStatus.COMPLETED)
        self.assertEqual(runtime.state, AgentState.COMPLETED)
        self.assertIn(AgentState.VERIFYING, state_history)


class TestStabilizationFix2ExactActionApprovalBinding(unittest.IsolatedAsyncioTestCase):
    """FIX #2 Regression tests: Human approval must bind to exact action identity and arguments."""

    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_memory.db"
        self.memory = SQLiteMemoryStore(db_path=self.db_path)

        self.policy = DefaultActionPolicy()
        self.registry = ToolRegistry()
        self.payment_tool = MockPaymentTool()
        self.registry.register(self.payment_tool)

    async def asyncTearDown(self):
        self.tmp_dir.cleanup()

    async def test_fingerprint_canonicalization(self):
        """Test that canonical argument formatting produces identical fingerprints regardless of key ordering."""
        fp1 = compute_action_fingerprint("authorize_invoice_payment", {"invoice_id": "INV-1", "amount": 10000})
        fp2 = compute_action_fingerprint("authorize_invoice_payment", {"amount": 10000, "invoice_id": "INV-1"})
        fp_diff = compute_action_fingerprint("authorize_invoice_payment", {"invoice_id": "INV-1", "amount": 1000000})

        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp_diff)

    def _payment_plan(self, amount=10000, invoice_id="INV-1"):
        return {
            "goal": "Pay invoice",
            "steps": ["Authorize payment"],
            "actions": [{"tool_name": "authorize_invoice_payment", "arguments": {"invoice_id": invoice_id, "amount": amount}}],
        }

    async def test_same_tool_same_args_approval_succeeds(self):
        """A. Same tool + same arguments -> approval succeeds."""
        llm = DummyMockLLM(
            responses=[
                {"is_complete": True, "action": None, "completion_summary": "Paid"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm,
        )

        task = Task(user_goal="Pay Acme Invoice")
        task = await runtime.execute_task(task)

        self.assertEqual(task.status, TaskStatus.WAITING_FOR_HUMAN)
        pending_fp = task.metadata.get("pending_action_fingerprint")
        self.assertIsNotNone(pending_fp)

        # Human approves
        approved_task = runtime.approve_task(task.task_id)
        self.assertEqual(approved_task.status, TaskStatus.RUNNING)
        self.assertEqual(approved_task.metadata.get("approved_action_fingerprint"), pending_fp)

        # Resume execution
        completed_task = await runtime.resume_task(task.task_id)
        self.assertEqual(completed_task.status, TaskStatus.COMPLETED)
        self.assertEqual(len(runtime.executed_actions), 1)
        self.assertEqual(runtime.executed_actions[0].arguments["amount"], 10000)

    async def test_modified_amount_rejected(self):
        """B. Same tool + modified amount -> approval rejected."""
        initial_action = {
            "tool_name": "authorize_invoice_payment",
            "arguments": {"invoice_id": "INV-1", "amount": 10000},
        }
        tampered_action = {
            "tool_name": "authorize_invoice_payment",
            "arguments": {"invoice_id": "INV-1", "amount": 1000000},  # Tampered!
        }

        llm = DummyMockLLM(
            responses=[
                {"is_complete": False, "action": initial_action, "reasoning": "Pay invoice"},
                # After resume, planner tries to execute tampered amount
                {"is_complete": False, "action": tampered_action, "reasoning": "Pay modified amount"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm,
        )

        task = Task(user_goal="Pay Acme Invoice")
        task = await runtime.execute_task(task)
        self.assertEqual(task.status, TaskStatus.WAITING_FOR_HUMAN)

        # Human approves original $10,000
        approved_task = runtime.approve_task(task.task_id)

        # Mutate the pending action arguments in task metadata to tampered amount $1,000,000
        approved_task.metadata["pending_action"]["arguments"]["amount"] = 1000000
        self.memory.update_task_state(
            task.task_id,
            state=AgentState.ADAPTING,
            status=TaskStatus.RUNNING,
            metadata=approved_task.metadata,
        )

        # Resume execution - runtime validates fingerprint and rejects
        result_task = await runtime.resume_task(task.task_id)

        # Must NOT execute tampered action, and must fail or block execution
        self.assertEqual(result_task.status, TaskStatus.FAILED)
        self.assertIn("fingerprint mismatch", result_task.metadata.get("error", "").lower())
        self.assertEqual(len(runtime.executed_actions), 0)

    async def test_modified_invoice_id_rejected(self):
        """C. Same tool + modified invoice ID -> approval rejected."""
        initial_action = {
            "tool_name": "authorize_invoice_payment",
            "arguments": {"invoice_id": "INV-1", "amount": 10000},
        }

        llm = DummyMockLLM(
            responses=[
                {"is_complete": False, "action": initial_action, "reasoning": "Pay invoice"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm,
        )

        task = await runtime.execute_task(Task(user_goal="Pay Invoice"))
        approved_task = runtime.approve_task(task.task_id)

        # Mutate invoice ID in metadata
        approved_task.metadata["pending_action"]["arguments"]["invoice_id"] = "INV-MALICIOUS-99"
        self.memory.update_task_state(
            task.task_id,
            state=AgentState.ADAPTING,
            status=TaskStatus.RUNNING,
            metadata=approved_task.metadata,
        )

        result = await runtime.resume_task(task.task_id)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("fingerprint mismatch", result.metadata.get("error", "").lower())
        self.assertEqual(len(runtime.executed_actions), 0)

    async def test_extra_argument_rejected(self):
        """D. Same tool + extra argument -> approval rejected."""
        initial_action = {
            "tool_name": "authorize_invoice_payment",
            "arguments": {"invoice_id": "INV-1", "amount": 10000},
        }

        llm = DummyMockLLM(
            responses=[
                {"is_complete": False, "action": initial_action, "reasoning": "Pay invoice"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm,
        )

        task = await runtime.execute_task(Task(user_goal="Pay Invoice"))
        approved_task = runtime.approve_task(task.task_id)

        # Mutate to inject extra argument
        approved_task.metadata["pending_action"]["arguments"]["skip_audit"] = True
        self.memory.update_task_state(
            task.task_id,
            state=AgentState.ADAPTING,
            status=TaskStatus.RUNNING,
            metadata=approved_task.metadata,
        )

        result = await runtime.resume_task(task.task_id)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("fingerprint mismatch", result.metadata.get("error", "").lower())
        self.assertEqual(len(runtime.executed_actions), 0)

    async def test_modified_nested_argument_rejected(self):
        """E. Modified nested argument -> approval rejected."""
        fp1 = compute_action_fingerprint("custom_tool", {"details": {"nested_flag": False}})
        fp2 = compute_action_fingerprint("custom_tool", {"details": {"nested_flag": True}})
        self.assertNotEqual(fp1, fp2)

    async def test_approval_reuse_rejected(self):
        """F. Reusing the same approval twice -> second attempt rejected (single-use)."""
        action = {
            "tool_name": "authorize_invoice_payment",
            "arguments": {"invoice_id": "INV-1", "amount": 10000},
        }
        # Planner attempts to run the exact same payment action twice in a row
        llm = DummyMockLLM(
            responses=[
                {"is_complete": False, "action": action, "reasoning": "Pay invoice"},
                {"is_complete": False, "action": action, "reasoning": "Pay same invoice again"},
                {"is_complete": True, "action": None, "completion_summary": "Done"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm,
        )

        task = await runtime.execute_task(Task(user_goal="Pay invoice twice"))
        runtime.approve_task(task.task_id)

        # First resumption executes the action, consuming the approval token
        resumed = await runtime.resume_task(task.task_id)

        # Since planner requests another financial action, policy engine requires a fresh approval
        self.assertEqual(resumed.status, TaskStatus.WAITING_FOR_HUMAN)
        # Exactly one action executed
        self.assertEqual(len(runtime.executed_actions), 1)

    async def test_approval_survives_runtime_recreation(self):
        """G. Approval survives runtime recreation -> exact approved action still works."""
        action = {
            "tool_name": "authorize_invoice_payment",
            "arguments": {"invoice_id": "INV-1", "amount": 10000},
        }
        llm1 = DummyMockLLM(
            responses=[
                {"is_complete": False, "action": action, "reasoning": "Pay invoice"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime1 = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm1,
        )

        task = await runtime1.execute_task(Task(user_goal="Pay Acme Invoice"))
        runtime1.approve_task(task.task_id)

        # Simulate complete server restart: create completely fresh runtime instance with same sqlite DB
        llm2 = DummyMockLLM(
            responses=[
                {"is_complete": True, "action": None, "completion_summary": "Done"},
            ],
            initial_plan=self._payment_plan(),
        )
        runtime2 = AgentRuntime(
            tool_registry=self.registry,
            memory_store=self.memory,
            policy=self.policy,
            llm_provider=llm2,
        )

        completed_task = await runtime2.resume_task(task.task_id)

        self.assertEqual(completed_task.status, TaskStatus.COMPLETED)
        self.assertEqual(len(runtime2.executed_actions), 1)


class TestStabilizationFix3IndependentFinanceVerification(unittest.IsolatedAsyncioTestCase):
    """FIX #3 Regression tests: Independent source-of-truth verification."""

    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.source_file = Path(self.tmp_dir.name) / "test_invoice.txt"
        self.source_file.write_text(
            """INVOICE RECORD
Invoice ID: INV-2026-9999
Vendor: Globex Corporation
Date: 2026-03-25
Amount: $18,036.00
Due Date: 2026-04-25
Status: APPROVED
""",
            encoding="utf-8",
        )
        self.verifier = FinanceInvoiceVerifier()

    async def asyncTearDown(self):
        self.tmp_dir.cleanup()

    async def test_parse_source_document(self):
        """Verify independent parsing of source document."""
        data = parse_source_document(str(self.source_file))
        self.assertEqual(data["invoice_id"], "INV-2026-9999")
        self.assertEqual(data["company"], "Globex Corporation")
        self.assertEqual(data["amount"], "18036.00")
        self.assertEqual(data["invoice_date"], "2026-03-25")
        self.assertEqual(data["due_date"], "2026-04-25")

    async def test_correct_source_and_correct_portal_state_verified(self):
        """A. Correct source + correct portal state -> VERIFIED."""
        portal_invoice = {
            "id": "INV-2026-9999",
            "company": "Globex Corporation",
            "amount": "18036.00",
            "invoice_date": "2026-03-25",
            "due_date": "2026-04-25",
        }
        with patch.object(self.verifier, "fetch_portal_invoice", return_value=portal_invoice):
            result = await self.verifier.verify(
                task_metadata={"source_document": str(self.source_file)},
                source_reference=str(self.source_file),
            )
            self.assertTrue(result.is_verified)
            self.assertEqual(result.actual["id"], "INV-2026-9999")

    async def test_source_amount_mismatch_fails_verification(self):
        """B. Source says $18,036 but portal contains $1,803.60 -> verification FAILS."""
        portal_invoice = {
            "id": "INV-2026-9999",
            "company": "Globex Corporation",
            "amount": "1803.60",  # Misplaced decimal point in portal!
            "invoice_date": "2026-03-25",
            "due_date": "2026-04-25",
        }
        with patch.object(self.verifier, "fetch_portal_invoice", return_value=portal_invoice):
            result = await self.verifier.verify(
                task_metadata={"source_document": str(self.source_file)},
                source_reference=str(self.source_file),
            )
            self.assertFalse(result.is_verified)
            self.assertIn("amount: expected '18036.00', got '1803.60'", result.details)

    async def test_browser_mistyped_amount_fails_verification(self):
        """C. Browser actions contain mistyped amount and portal matches wrong amount -> verification FAILS."""
        portal_invoice = {
            "id": "INV-2026-9999",
            "company": "Globex Corporation",
            "amount": "1803.60",
            "invoice_date": "2026-03-25",
            "due_date": "2026-04-25",
        }
        with patch.object(self.verifier, "fetch_portal_invoice", return_value=portal_invoice):
            result = await self.verifier.verify(
                task_metadata={
                    "source_document": str(self.source_file),
                    "browser_typed_amount": "1803.60",  # Even if metadata claims it typed 1803.60
                },
                source_reference=str(self.source_file),
            )
            self.assertFalse(result.is_verified)
            self.assertIn("amount: expected '18036.00', got '1803.60'", result.details)

    async def test_missing_source_document_fails_safely(self):
        """D. Missing source document -> verification fails safely."""
        result = await self.verifier.verify(
            task_metadata={},
            source_reference="non_existent_invoice_file.txt",
        )
        self.assertFalse(result.is_verified)
        self.assertIn("Missing source document", result.details)


class TestStabilizationFix4BrowserPortConfig(unittest.IsolatedAsyncioTestCase):
    """FIX #4 Regression tests: Configurable browser navigation ports."""

    def test_default_allowed_ports(self):
        """Default allowed ports are {3000, 3001}."""
        with patch.dict(os.environ, {}, clear=True):
            ports = get_allowed_ports()
            self.assertIn(3000, ports)
            self.assertIn(3001, ports)
            self.assertNotIn(9999, ports)

    def test_custom_allowed_ports_from_env(self):
        """Configuring AURA_BROWSER_ALLOWED_PORTS parses valid integers."""
        with patch.dict(os.environ, {"AURA_BROWSER_ALLOWED_PORTS": "8000, 8080, 443"}):
            ports = get_allowed_ports()
            self.assertEqual(ports, {8000, 8080, 443})

    def test_malformed_port_env_handling(self):
        """Malformed or negative port values are filtered out without crashing."""
        with patch.dict(os.environ, {"AURA_BROWSER_ALLOWED_PORTS": "abc, 8000, -1, 999999, 80"}):
            ports = get_allowed_ports()
            self.assertEqual(ports, {8000, 80})

    async def test_navigation_rejects_unconfigured_port(self):
        """BrowserNavigateTool rejects navigation to unallowed port."""
        tool = BrowserNavigateTool()
        obs = await tool.execute(url="http://localhost:9999/secret")
        self.assertFalse(obs.success)
        self.assertIn("outside permitted local origins", obs.error)

    async def test_navigation_allows_configured_port(self):
        """BrowserNavigateTool allows navigation to port in configured list."""
        mock_page = AsyncMock()
        mock_session = MagicMock(spec=BrowserSession)
        mock_session.get_page = AsyncMock(return_value=mock_page)

        tool = BrowserNavigateTool(session=mock_session)
        with patch.dict(os.environ, {"AURA_BROWSER_ALLOWED_PORTS": "8080"}):
            obs = await tool.execute(url="http://localhost:8080/dashboard")
            self.assertTrue(obs.success)
            mock_page.goto.assert_called_once()


class TestStabilizationFix5CORSHardening(unittest.TestCase):
    """FIX #5 Regression tests: Non-wildcard CORS configuration."""

    def test_default_allowed_origins_no_wildcard(self):
        """Ensure default origins do NOT contain wildcard '*'."""
        with patch.dict(os.environ, {}, clear=True):
            origins = get_allowed_origins()
            self.assertNotIn("*", origins)
            self.assertIn("http://localhost:3000", origins)
            self.assertIn("http://localhost:3001", origins)

    def test_custom_allowed_origins_from_env(self):
        """Configuring AURA_ALLOWED_ORIGINS parses specific origins."""
        with patch.dict(os.environ, {"AURA_ALLOWED_ORIGINS": "https://aura.internal, http://test.local:5000"}):
            origins = get_allowed_origins()
            self.assertIn("https://aura.internal", origins)
            self.assertIn("http://test.local:5000", origins)
            self.assertNotIn("*", origins)

    def test_fastapi_app_cors_middleware_has_no_wildcard(self):
        """Ensure CORSMiddleware attached to FastAPI does not allow '*'."""
        for middleware in app.user_middleware:
            if "CORSMiddleware" in str(middleware.cls):
                allow_origins = middleware.kwargs.get("allow_origins", [])
                self.assertNotIn("*", allow_origins)


class TestStabilizationFix6BrowserTypeJSSafety(unittest.IsolatedAsyncioTestCase):
    """FIX #6 Regression tests: Safe argument passing for browser_type JavaScript evaluation."""

    async def test_browser_type_quotes_and_special_chars_safe(self):
        """Ensure browser_type handles quotes, backticks, and injection strings safely."""
        mock_locator = AsyncMock()
        mock_locator.get_attribute = AsyncMock(return_value="date")
        mock_locator.wait_for = AsyncMock()
        mock_locator.fill = AsyncMock()
        mock_locator.evaluate = AsyncMock()

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(return_value=MagicMock(first=mock_locator))

        mock_session = MagicMock(spec=BrowserSession)
        mock_session.get_page = AsyncMock(return_value=mock_page)

        tool = BrowserTypeTool(session=mock_session)

        # Tricky input with quotes, semicolon, and JS injection attempt
        malicious_or_complex_text = "2026-03-20'; alert('pwned'); //"
        obs = await tool.execute(selector="input[name='invoice_date']", text=malicious_or_complex_text)

        self.assertTrue(obs.success)
        # Verify evaluate was called with function and parameterized argument, NOT interpolated string
        mock_locator.evaluate.assert_called_once()
        call_args = mock_locator.evaluate.call_args
        js_func = call_args[0][0]
        passed_val = call_args[0][1]

        self.assertIn("(element, value) =>", js_func)
        self.assertEqual(passed_val, malicious_or_complex_text)
        self.assertNotIn(malicious_or_complex_text, js_func)


if __name__ == "__main__":
    unittest.main()
