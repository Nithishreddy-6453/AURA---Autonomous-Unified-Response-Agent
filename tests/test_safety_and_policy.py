import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.schemas import NextActionResponseSchema
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.memory.base import MemoryStore, TaskRecord
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.policy.decision import PolicyDecision
from backend.policy.engine import ActionPolicy, DefaultActionPolicy
from backend.policy.risk import ActionRisk
from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry


class SequenceMockLLM(LLMProvider):
    """Deterministic LLM mock returning a programmed sequence of planning responses."""

    def __init__(self, initial_plan: dict, step_responses: List[dict]):
        self.initial_plan = initial_plan
        self.step_responses = step_responses
        self.step_index = 0
        self.prompts_received: List[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        self.prompts_received.append(prompt)
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps(self.initial_plan)

        if self.step_index < len(self.step_responses):
            resp = self.step_responses[self.step_index]
            self.step_index += 1
            return json.dumps(resp)

        return json.dumps({
            "is_complete": True,
            "completion_summary": "Default completed.",
            "action": None,
        })

    async def chat(self, messages: list, temperature: float = 0.0, **kwargs: Any) -> str:
        return await self.generate(messages[-1]["content"])


class MockCustomTool(Tool):
    """Configurable mock tool exposing specific risk levels and tracking execution calls."""

    def __init__(
        self,
        tool_name: str,
        risk: ActionRisk = ActionRisk.READ,
        return_value: Any = "success",
    ):
        self._name = tool_name
        self._risk = risk
        self.return_value = return_value
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock tool {self._name} with risk {self._risk.value}"

    @property
    def risk_level(self) -> ActionRisk:
        return self._risk

    @property
    def capabilities(self) -> List[str]:
        return ["test", self._risk.value.lower()]

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "payload": {"type": "string"},
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        self.call_count += 1
        self.calls.append(kwargs)
        return Observation(
            action_id=str(uuid4()),
            success=True,
            result={"output": self.return_value, "call_count": self.call_count},
        )


class TestPolicyEngineUnit(unittest.TestCase):
    """Unit tests for ActionRisk, PolicyDecision, and DefaultActionPolicy evaluation."""

    def setUp(self):
        self.policy = DefaultActionPolicy(
            sensitive_tools={"submit_payment", "wire_funds"},
            destructive_tools={"delete_invoice", "purge_all_records"},
        )
        self.task = Task(user_goal="Test safety policies")

    def test_read_action_allowed(self):
        """A: READ action is allowed."""
        read_tool = MockCustomTool("browser_read", risk=ActionRisk.READ)
        action = Action(tool_name="browser_read", arguments={"selector": "h1"})

        decision = self.policy.evaluate(self.task, action, read_tool)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_human)
        self.assertFalse(decision.blocked)
        self.assertEqual(decision.risk_level, ActionRisk.READ)

    def test_normal_write_action_allowed_in_sandbox(self):
        """B: Normal WRITE action is allowed in sandbox mode."""
        write_tool = MockCustomTool("browser_type", risk=ActionRisk.WRITE)
        action = Action(
            tool_name="browser_type",
            arguments={"target": "company", "text": "Acme Corp"},
        )

        decision = self.policy.evaluate(self.task, action, write_tool)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_human)
        self.assertFalse(decision.blocked)
        self.assertEqual(decision.risk_level, ActionRisk.WRITE)

    def test_sensitive_action_requires_human(self):
        """C: SENSITIVE action requires human approval."""
        sensitive_tool = MockCustomTool("submit_payment", risk=ActionRisk.SENSITIVE)
        action = Action(
            tool_name="submit_payment",
            arguments={"amount": 5000, "recipient": "Acme Corp"},
        )

        decision = self.policy.evaluate(self.task, action, sensitive_tool)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_human)
        self.assertFalse(decision.blocked)
        self.assertEqual(decision.risk_level, ActionRisk.SENSITIVE)
        self.assertIn("requires human approval", decision.reason)

    def test_destructive_action_blocked(self):
        """D: DESTRUCTIVE action is blocked."""
        destruct_tool = MockCustomTool("delete_invoice", risk=ActionRisk.DESTRUCTIVE)
        action = Action(tool_name="delete_invoice", arguments={"id": "INV-100"})

        decision = self.policy.evaluate(self.task, action, destruct_tool)
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_human)
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.risk_level, ActionRisk.DESTRUCTIVE)
        self.assertIn("blocked by safety policy", decision.reason)

    def test_destructive_keyword_in_arguments_blocked(self):
        """D2: Normal tool with destructive payload is detected and blocked."""
        click_tool = MockCustomTool("browser_click", risk=ActionRisk.WRITE)
        action = Action(
            tool_name="browser_click",
            arguments={"target": "Delete Database Record"},
        )

        decision = self.policy.evaluate(self.task, action, click_tool)
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.risk_level, ActionRisk.DESTRUCTIVE)

    def test_unknown_tool_cannot_execute(self):
        """E: Unknown tool cannot execute and is blocked."""
        action = Action(tool_name="unregistered_tool", arguments={})
        decision = self.policy.evaluate(self.task, action, None)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.blocked)
        self.assertIn("not registered or permitted", decision.reason)


class TestRuntimePolicyEnforcement(unittest.TestCase):
    """Integration tests verifying policy enforcement, human approval, and resume lifecycle."""

    def setUp(self):
        self.store = SQLiteMemoryStore(":memory:")
        self.tool_reg = ToolRegistry()

        self.read_tool = MockCustomTool("safe_read", risk=ActionRisk.READ)
        self.write_tool = MockCustomTool("safe_write", risk=ActionRisk.WRITE)
        self.sensitive_tool = MockCustomTool("submit_payment", risk=ActionRisk.SENSITIVE)
        self.destructive_tool = MockCustomTool("delete_record", risk=ActionRisk.DESTRUCTIVE)

        self.tool_reg.register(self.read_tool)
        self.tool_reg.register(self.write_tool)
        self.tool_reg.register(self.sensitive_tool)
        self.tool_reg.register(self.destructive_tool)

        self.policy = DefaultActionPolicy(
            sensitive_tools={"submit_payment"},
            destructive_tools={"delete_record"},
        )

    def tearDown(self):
        self.store.close()

    def test_policy_checked_before_execution_and_blocked_never_executes(self):
        """F & G: Policy is checked before execution; blocked action never reaches Tool.execute()."""
        runtime = AgentRuntime(
            llm_provider=SequenceMockLLM({}, []),
            tool_registry=self.tool_reg,
            memory_store=self.store,
            policy=self.policy,
        )

        task = Task(user_goal="Attempt destructive action")
        self.store.create_task(task)

        action = Action(tool_name="delete_record", arguments={"target": "all"})
        obs = asyncio.run(runtime._execute_single_action(action, task))

        self.assertFalse(obs.success)
        self.assertIn("blocked by policy", obs.error.lower())
        self.assertEqual(self.destructive_tool.call_count, 0)
        self.assertEqual(action.status, ActionStatus.FAILED)

    def test_sensitive_action_pauses_in_waiting_for_human(self):
        """H: SENSITIVE action pauses in WAITING_FOR_HUMAN and state is persisted."""
        mock_llm = SequenceMockLLM(
            initial_plan={
                "goal": "Pay invoice",
                "is_feasible": True,
                "actions": [{"tool_name": "safe_read", "arguments": {}}],
            },
            step_responses=[
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "submit_payment",
                        "arguments": {"amount": 1000},
                    },
                    "reasoning": "Step requires payment submission",
                }
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_reg,
            memory_store=self.store,
            policy=self.policy,
        )

        task = Task(user_goal="Process invoice with payment")
        res_task = asyncio.run(runtime.execute_task(task))

        self.assertEqual(res_task.status, TaskStatus.WAITING_FOR_HUMAN)
        self.assertEqual(runtime.state, AgentState.WAITING_FOR_HUMAN)
        self.assertEqual(self.sensitive_tool.call_count, 0)
        self.assertIsNotNone(res_task.metadata.get("pending_action"))
        self.assertEqual(
            res_task.metadata["pending_action"]["tool_name"], "submit_payment"
        )

        # Confirm persisted state in SQLite
        record = self.store.get_task(task.task_id)
        self.assertEqual(record.task.status, TaskStatus.WAITING_FOR_HUMAN)
        self.assertEqual(record.state, AgentState.WAITING_FOR_HUMAN)

    def test_approval_allows_action_and_resumes_to_completion(self):
        """J & K: Approval allows the action to execute, and task resumes after approval."""
        mock_llm = SequenceMockLLM(
            initial_plan={
                "goal": "Execute payment flow",
                "is_feasible": True,
                "actions": [{"tool_name": "safe_read", "arguments": {}}],
            },
            step_responses=[
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "submit_payment",
                        "arguments": {"amount": 2500},
                    },
                    "reasoning": "Payment execution step",
                },
                {
                    "is_complete": True,
                    "completion_summary": "Payment successfully authorized and recorded.",
                    "action": None,
                },
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_reg,
            memory_store=self.store,
            policy=self.policy,
        )

        task = Task(user_goal="Approve and finish payment")
        task_id = task.task_id

        # Phase 1: Executes until WAITING_FOR_HUMAN
        asyncio.run(runtime.execute_task(task))
        self.assertEqual(runtime.state, AgentState.WAITING_FOR_HUMAN)
        self.assertEqual(self.sensitive_tool.call_count, 0)

        # Phase 2: Operator grants human approval
        runtime.approve_task(task_id, feedback="Approved by Finance Manager")

        # Phase 3: Resume task
        resumed_task = asyncio.run(runtime.resume_task(task_id))
        self.assertEqual(resumed_task.status, TaskStatus.COMPLETED)
        self.assertEqual(runtime.state, AgentState.COMPLETED)
        # Sensitive tool was executed exactly once following approval
        self.assertEqual(self.sensitive_tool.call_count, 1)

    def test_pending_approval_survives_runtime_recreation(self):
        """I: Pending approval survives Runtime recreation (process restart)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "policy_memory.db"

            # Shared tools
            tools = ToolRegistry()
            t_read = MockCustomTool("safe_read", risk=ActionRisk.READ)
            t_pay = MockCustomTool("submit_payment", risk=ActionRisk.SENSITIVE)
            tools.register(t_read)
            tools.register(t_pay)

            policy = DefaultActionPolicy(sensitive_tools={"submit_payment"})

            # Runtime 1: Runs task and hits WAITING_FOR_HUMAN
            store_1 = SQLiteMemoryStore(db_path)
            llm_1 = SequenceMockLLM(
                initial_plan={
                    "goal": "Pay vendor",
                    "is_feasible": True,
                    "actions": [{"tool_name": "safe_read", "arguments": {}}],
                },
                step_responses=[
                    {
                        "is_complete": False,
                        "action": {
                            "tool_name": "submit_payment",
                            "arguments": {"amount": 7500},
                        },
                        "reasoning": "Need wire payment",
                    }
                ],
            )
            runtime_1 = AgentRuntime(
                llm_provider=llm_1,
                tool_registry=tools,
                memory_store=store_1,
                policy=policy,
            )

            task = Task(user_goal="Transfer payment with process crash")
            task_id = task.task_id
            asyncio.run(runtime_1.execute_task(task))
            self.assertEqual(runtime_1.state, AgentState.WAITING_FOR_HUMAN)
            store_1.close()

            # Destroy Runtime 1 completely
            del runtime_1

            # Runtime 2: Brand new instance on same SQLite DB
            store_2 = SQLiteMemoryStore(db_path)
            llm_2 = SequenceMockLLM(
                initial_plan={},
                step_responses=[
                    {
                        "is_complete": True,
                        "completion_summary": "Wire transfer finished after crash recovery.",
                        "action": None,
                    }
                ],
            )
            runtime_2 = AgentRuntime(
                llm_provider=llm_2,
                tool_registry=tools,
                memory_store=store_2,
                policy=policy,
            )

            # Check that unapproved task remains non-resumable
            reloaded = asyncio.run(runtime_2.resume_task(task_id))
            self.assertEqual(reloaded.status, TaskStatus.WAITING_FOR_HUMAN)
            self.assertEqual(t_pay.call_count, 0)

            # Approve via Runtime 2
            runtime_2.approve_task(task_id, feedback="Approved after server restart")

            # Resume via Runtime 2
            final_task = asyncio.run(runtime_2.resume_task(task_id))
            self.assertEqual(final_task.status, TaskStatus.COMPLETED)
            self.assertEqual(t_pay.call_count, 1)

            # Verify persisted memory in store_2
            record = store_2.get_task(task_id)
            self.assertEqual(record.task.status, TaskStatus.COMPLETED)
            self.assertEqual(record.state, AgentState.COMPLETED)
            store_2.close()

    def test_repeated_blocked_actions_cannot_create_infinite_loops(self):
        """L: Repeated blocked actions cannot create infinite loops."""
        mock_llm = SequenceMockLLM(
            initial_plan={
                "goal": "Loop test",
                "is_feasible": True,
                "actions": [{"tool_name": "safe_read", "arguments": {}}],
            },
            step_responses=[
                # LLM repeatedly insists on the same destructive action
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "delete_record",
                        "arguments": {"target": "all"},
                    },
                    "reasoning": "Attempt 1",
                },
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "delete_record",
                        "arguments": {"target": "all"},
                    },
                    "reasoning": "Attempt 2",
                },
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "delete_record",
                        "arguments": {"target": "all"},
                    },
                    "reasoning": "Attempt 3",
                },
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_reg,
            memory_store=self.store,
            policy=self.policy,
            max_dynamic_steps=10,
        )

        task = Task(user_goal="Attempt infinite destructive loop")
        res_task = asyncio.run(runtime.execute_task(task))

        self.assertEqual(res_task.status, TaskStatus.FAILED)
        self.assertIn("loop detected", res_task.metadata.get("error", "").lower())
        self.assertEqual(self.destructive_tool.call_count, 0)

    def test_policy_events_persisted_in_memory(self):
        """M: Policy events and decisions are persisted in task memory."""
        mock_llm = SequenceMockLLM(
            initial_plan={
                "goal": "Audit trail test",
                "is_feasible": True,
                "actions": [{"tool_name": "safe_read", "arguments": {}}],
            },
            step_responses=[
                {
                    "is_complete": False,
                    "action": {"tool_name": "safe_write", "arguments": {"payload": "abc"}},
                    "reasoning": "Write step",
                },
                {
                    "is_complete": True,
                    "completion_summary": "Audit test done",
                    "action": None,
                },
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_reg,
            memory_store=self.store,
            policy=self.policy,
        )

        task = Task(user_goal="Generate policy audit trail")
        asyncio.run(runtime.execute_task(task))

        record = self.store.get_task(task.task_id)
        self.assertIsNotNone(record)
        self.assertGreaterEqual(len(record.policy_events), 2)
        # Check risk level and decisions recorded
        risks_logged = [e.get("risk_level") for e in record.policy_events if "risk_level" in e]
        self.assertIn("READ", risks_logged)
        self.assertIn("WRITE", risks_logged)


class TestFinancePortalPolicyDemonstration(unittest.TestCase):
    """Section 14: Demonstration test with controlled sensitive approval in Finance workflow."""

    def test_controlled_sensitive_action_requires_approval_and_completes(self):
        """Demonstrates controlled financial workflow:
        1. Normal actions proceed automatically.
        2. SENSITIVE action (Authorize Invoice Payment) requests human approval.
        3. Runtime halts in WAITING_FOR_HUMAN.
        4. Operator approves.
        5. Runtime resumes, executes action, and completes.
        """
        store = SQLiteMemoryStore(":memory:")
        tools = ToolRegistry()

        t_search = MockCustomTool("search_company_files", risk=ActionRisk.READ)
        t_read = MockCustomTool("read_company_file", risk=ActionRisk.READ)
        t_type = MockCustomTool("browser_type", risk=ActionRisk.WRITE)
        t_auth = MockCustomTool("authorize_invoice_payment", risk=ActionRisk.SENSITIVE)

        tools.register(t_search)
        tools.register(t_read)
        tools.register(t_type)
        tools.register(t_auth)

        policy = DefaultActionPolicy(sensitive_tools={"authorize_invoice_payment"})

        mock_llm = SequenceMockLLM(
            initial_plan={
                "goal": "Find latest Acme invoice and enter into Finance Portal",
                "is_feasible": True,
                "actions": [
                    {
                        "tool_name": "search_company_files",
                        "arguments": {"query": "Acme invoice"},
                    }
                ],
            },
            step_responses=[
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "read_company_file",
                        "arguments": {"file_path": "invoices/acme_invoice_2026_03.txt"},
                    },
                    "reasoning": "Read invoice file",
                },
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "browser_type",
                        "arguments": {"target": "amount", "text": "18036.00"},
                    },
                    "reasoning": "Fill invoice amount into Finance Portal",
                },
                {
                    "is_complete": False,
                    "action": {
                        "tool_name": "authorize_invoice_payment",
                        "arguments": {
                            "invoice_id": "INV-2026-0089",
                            "amount": "18036.00",
                        },
                    },
                    "reasoning": "Trigger authorization for payment release",
                },
                {
                    "is_complete": True,
                    "completion_summary": "Invoice entered and authorized successfully.",
                    "action": None,
                },
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=tools,
            memory_store=store,
            policy=policy,
        )

        task = Task(
            user_goal="Find the latest Acme invoice and enter the amount into the Finance Portal."
        )
        task_id = task.task_id

        # Phase 1: Execution proceeds automatically for search, read, type,
        # then hits SENSITIVE authorization action.
        asyncio.run(runtime.execute_task(task))

        self.assertEqual(runtime.state, AgentState.WAITING_FOR_HUMAN)
        self.assertEqual(task.status, TaskStatus.WAITING_FOR_HUMAN)
        self.assertEqual(t_search.call_count, 1)
        self.assertEqual(t_read.call_count, 1)
        self.assertEqual(t_type.call_count, 1)
        # Sensitive authorization action has NOT executed yet
        self.assertEqual(t_auth.call_count, 0)

        # Phase 2: Operator reviews and approves
        runtime.approve_task(task_id, feedback="Invoice INV-2026-0089 verified and approved.")

        # Phase 3: Resume
        completed_task = asyncio.run(runtime.resume_task(task_id))

        self.assertEqual(completed_task.status, TaskStatus.COMPLETED)
        self.assertEqual(runtime.state, AgentState.COMPLETED)
        # Sensitive authorization action was executed upon approval
        self.assertEqual(t_auth.call_count, 1)
        store.close()


if __name__ == "__main__":
    unittest.main()
