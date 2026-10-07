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
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus
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


class MockExecutionTool(Tool):
    """Simple configurable mock tool for memory and resume tests."""

    def __init__(self, tool_name: str, return_value: Any = "success"):
        self._name = tool_name
        self._description = f"Mock execution tool {tool_name}"
        self.return_value = return_value
        self.call_history: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "val": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        self.call_history.append(kwargs)
        return Observation(
            action_id=str(uuid4()),
            success=True,
            result={"output": self.return_value, "args": kwargs},
        )


class TestSQLiteMemoryStoreUnit(unittest.TestCase):
    """Unit tests for SQLiteMemoryStore operations in memory and temporary file DBs."""

    def setUp(self):
        self.store = SQLiteMemoryStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_create_and_get_task(self):
        """A & B: Create and persist a task, load the same task by ID."""
        task = Task(user_goal="Process quarterly fiscal report")
        self.store.create_task(task, initial_state=AgentState.RECEIVED)

        record = self.store.get_task(task.task_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.task.task_id, task.task_id)
        self.assertEqual(record.task.user_goal, "Process quarterly fiscal report")
        self.assertEqual(record.task.status, TaskStatus.PENDING)
        self.assertEqual(record.state, AgentState.RECEIVED)
        self.assertEqual(len(record.actions), 0)
        self.assertEqual(len(record.observations), 0)

    def test_get_nonexistent_task(self):
        """Loading a non-existent task ID returns None."""
        record = self.store.get_task("nonexistent-id-999")
        self.assertIsNone(record)

    def test_persist_state_transitions(self):
        """C: Persist state transitions across lifecycle."""
        task = Task(user_goal="Reconcile inventory")
        self.store.create_task(task, initial_state=AgentState.RECEIVED)

        # Transition 1: PLANNING
        self.store.update_task_state(task.task_id, AgentState.PLANNING, status=TaskStatus.RUNNING)
        rec1 = self.store.get_task(task.task_id)
        self.assertEqual(rec1.state, AgentState.PLANNING)
        self.assertEqual(rec1.task.status, TaskStatus.RUNNING)

        # Transition 2: EXECUTING
        self.store.update_task_state(task.task_id, AgentState.EXECUTING)
        rec2 = self.store.get_task(task.task_id)
        self.assertEqual(rec2.state, AgentState.EXECUTING)
        self.assertEqual(rec2.task.status, TaskStatus.RUNNING)

        # Transition 3: COMPLETED
        self.store.update_task_state(
            task.task_id,
            AgentState.COMPLETED,
            status=TaskStatus.COMPLETED,
            metadata={"summary": "Reconciliation successful"},
        )
        rec3 = self.store.get_task(task.task_id)
        self.assertEqual(rec3.state, AgentState.COMPLETED)
        self.assertEqual(rec3.task.status, TaskStatus.COMPLETED)
        self.assertEqual(rec3.task.metadata.get("summary"), "Reconciliation successful")

    def test_append_and_retrieve_actions(self):
        """D: Append and retrieve actions."""
        task = Task(user_goal="Process orders")
        self.store.create_task(task)

        action1 = Action(
            action_id="act-1",
            tool_name="search_company_files",
            arguments={"query": "orders.csv"},
        )
        action2 = Action(
            action_id="act-2",
            tool_name="read_company_file",
            arguments={"path": "orders.csv"},
        )
        self.store.append_action(task.task_id, action1)
        self.store.append_action(task.task_id, action2)

        record = self.store.get_task(task.task_id)
        self.assertEqual(len(record.actions), 2)
        self.assertEqual(record.actions[0].tool_name, "search_company_files")
        self.assertEqual(record.actions[1].tool_name, "read_company_file")

        # Update action status
        action1.status = ActionStatus.SUCCESS
        self.store.append_action(task.task_id, action1)
        rec_updated = self.store.get_task(task.task_id)
        self.assertEqual(rec_updated.actions[0].status, ActionStatus.SUCCESS)

    def test_append_and_retrieve_observations(self):
        """E: Append and retrieve observations."""
        task = Task(user_goal="Download invoice")
        self.store.create_task(task)

        obs1 = Observation(
            action_id="act-1",
            success=True,
            result={"files": ["inv_1.pdf", "inv_2.pdf"]},
            metadata={"source": "filesystem"},
        )
        obs2 = Observation(
            action_id="act-2",
            success=False,
            error="File corrupt",
            metadata={"retryable": True},
        )
        self.store.append_observation(task.task_id, obs1)
        self.store.append_observation(task.task_id, obs2)

        record = self.store.get_task(task.task_id)
        self.assertEqual(len(record.observations), 2)
        self.assertTrue(record.observations[0].success)
        self.assertEqual(record.observations[0].result["files"], ["inv_1.pdf", "inv_2.pdf"])
        self.assertFalse(record.observations[1].success)
        self.assertEqual(record.observations[1].error, "File corrupt")
        self.assertEqual(record.observations[1].metadata["retryable"], True)

    def test_bounded_recent_history(self):
        """F: Recent-history retrieval is bounded."""
        task = Task(user_goal="Bounded test")
        self.store.create_task(task)

        # Add 8 actions and observations
        for i in range(8):
            act = Action(action_id=f"act-{i}", tool_name=f"tool_{i}", arguments={"step": i})
            obs = Observation(action_id=f"act-{i}", success=True, result={"step": i})
            self.store.append_action(task.task_id, act)
            self.store.append_observation(task.task_id, obs)

        recent_acts, recent_obs = self.store.get_recent_history(task.task_id, limit=3)
        self.assertEqual(len(recent_acts), 3)
        self.assertEqual(len(recent_obs), 3)
        self.assertEqual([a.action_id for a in recent_acts], ["act-5", "act-6", "act-7"])
        self.assertEqual([o.action_id for o in recent_obs], ["act-5", "act-6", "act-7"])

    def test_terminal_status_persists_correctly(self):
        """G: Terminal statuses (COMPLETED, FAILED, WAITING_FOR_HUMAN) persist correctly."""
        for term_status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.WAITING_FOR_HUMAN, TaskStatus.NEEDS_HUMAN]:
            task = Task(user_goal=f"Test {term_status.value}")
            self.store.create_task(task)
            state_val = AgentState(term_status.value)
            self.store.update_task_state(
                task.task_id,
                state=state_val,
                status=term_status,
                metadata={"final_note": f"Task ended with {term_status.value}"},
            )

            record = self.store.get_task(task.task_id)
            self.assertEqual(record.task.status, term_status)
            self.assertEqual(record.state, state_val)
            self.assertEqual(record.task.metadata["final_note"], f"Task ended with {term_status.value}")

    def test_save_and_retrieve_plan(self):
        """Plan persistence test."""
        task = Task(user_goal="Test plan persistence")
        self.store.create_task(task)

        plan = Plan(
            plan_id="plan-123",
            task_id=task.task_id,
            goal="Execute test plan",
            actions=[
                Action(tool_name="step_one", arguments={"a": 1}),
                Action(tool_name="step_two", arguments={"b": 2}),
            ],
        )
        self.store.save_plan(task.task_id, plan)

        record = self.store.get_task(task.task_id)
        self.assertIsNotNone(record.plan)
        self.assertEqual(record.plan.plan_id, "plan-123")
        self.assertEqual(len(record.plan.actions), 2)
        self.assertEqual(record.plan.actions[0].tool_name, "step_one")

    def test_recovery_events_persistence(self):
        """Recovery events persistence test."""
        task = Task(user_goal="Test recovery logging")
        self.store.create_task(task)

        event = {
            "source": "browser_navigate",
            "policy": "RETRY_WITH_BACKOFF",
            "error": "Connection timeout",
        }
        self.store.append_recovery_event(task.task_id, event)

        record = self.store.get_task(task.task_id)
        self.assertEqual(len(record.recovery_events), 1)
        self.assertEqual(record.recovery_events[0]["policy"], "RETRY_WITH_BACKOFF")


class TestRuntimeMemoryIntegration(unittest.TestCase):
    """Integration tests verifying AgentRuntime interaction with MemoryStore."""

    def setUp(self):
        self.tool_registry = ToolRegistry()
        self.t1 = MockExecutionTool("step_one", "result_1")
        self.t2 = MockExecutionTool("step_two", "result_2")
        self.tool_registry.register(self.t1)
        self.tool_registry.register(self.t2)
        self.store = SQLiteMemoryStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_runtime_persists_lifecycle_events(self):
        """Verify AgentRuntime records task creation, state transitions, actions, observations."""
        mock_llm = SequenceMockLLM(
            initial_plan={
                "goal": "Run step one and two",
                "is_feasible": True,
                "actions": [{"tool_name": "step_one", "arguments": {"x": 10}}],
            },
            step_responses=[
                {
                    "is_complete": False,
                    "action": {"tool_name": "step_two", "arguments": {"y": 20}},
                    "reasoning": "Step one succeeded, running step two",
                },
                {
                    "is_complete": True,
                    "completion_summary": "Both steps completed successfully",
                    "action": None,
                },
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_registry,
            memory_store=self.store,
        )

        task = Task(user_goal="Execute lifecycle test")
        asyncio.run(runtime.execute_task(task))

        record = self.store.get_task(task.task_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.task.status, TaskStatus.COMPLETED)
        self.assertEqual(record.state, AgentState.COMPLETED)
        self.assertEqual(len(record.actions), 2)
        self.assertEqual(len(record.observations), 2)
        self.assertEqual(record.actions[0].tool_name, "step_one")
        self.assertEqual(record.actions[1].tool_name, "step_two")
        self.assertTrue(record.observations[0].success)
        self.assertTrue(record.observations[1].success)

    def test_resume_non_terminal_task(self):
        """H: Resume a non-terminal task."""
        # Pre-seed a task in memory that was interrupted after step_one
        task = Task(task_id="interrupted-task-001", user_goal="Finish interrupted workflow")
        self.store.create_task(task, initial_state=AgentState.EXECUTING)

        act1 = Action(action_id="act-seed-1", tool_name="step_one", arguments={"x": 1})
        act1.status = ActionStatus.SUCCESS
        obs1 = Observation(action_id="act-seed-1", success=True, result={"output": "result_1"})
        self.store.append_action(task.task_id, act1)
        self.store.append_observation(task.task_id, obs1)
        self.store.update_task_state(task.task_id, AgentState.OBSERVING, status=TaskStatus.RUNNING)

        # Mock LLM provides step_two and then completion
        mock_llm = SequenceMockLLM(
            initial_plan={},
            step_responses=[
                {
                    "is_complete": False,
                    "action": {"tool_name": "step_two", "arguments": {"y": 2}},
                    "reasoning": "Step one was already done, proceed to step two",
                },
                {
                    "is_complete": True,
                    "completion_summary": "Resumed task completed",
                    "action": None,
                },
            ],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_registry,
            memory_store=self.store,
        )

        resumed_task = asyncio.run(runtime.resume_task(task.task_id))
        self.assertEqual(resumed_task.status, TaskStatus.COMPLETED)

        # Confirm step_one was NOT re-executed
        self.assertEqual(len(self.t1.call_history), 0)
        # Confirm step_two was executed
        self.assertEqual(len(self.t2.call_history), 1)

        # Confirm total history has both actions
        record = self.store.get_task(task.task_id)
        self.assertEqual(len(record.actions), 2)
        self.assertEqual(record.task.status, TaskStatus.COMPLETED)

    def test_completed_task_does_not_restart_automatically(self):
        """I: Completed tasks do not restart automatically when loaded."""
        task = Task(task_id="completed-task-002", user_goal="Already finished task")
        self.store.create_task(task)
        self.store.update_task_state(
            task.task_id,
            AgentState.COMPLETED,
            status=TaskStatus.COMPLETED,
            metadata={"final_result": "done"},
        )

        mock_llm = SequenceMockLLM(
            initial_plan={},
            step_responses=[{"is_complete": False, "action": {"tool_name": "step_one", "arguments": {}}}],
        )

        runtime = AgentRuntime(
            llm_provider=mock_llm,
            tool_registry=self.tool_registry,
            memory_store=self.store,
        )

        resumed = asyncio.run(runtime.resume_task(task.task_id))
        self.assertEqual(resumed.status, TaskStatus.COMPLETED)
        # LLM should not even be called
        self.assertEqual(len(mock_llm.prompts_received), 0)
        self.assertEqual(len(self.t1.call_history), 0)

    def test_waiting_for_human_preserves_context(self):
        """J: Waiting-for-human tasks preserve their context."""
        task = Task(task_id="human-wait-003", user_goal="Task needing approval")
        self.store.create_task(task)
        self.store.update_task_state(
            task.task_id,
            AgentState.NEEDS_HUMAN,
            status=TaskStatus.NEEDS_HUMAN,
            metadata={"human_intervention_reason": "User confirmation required for transfer"},
        )

        runtime = AgentRuntime(
            llm_provider=SequenceMockLLM({}, []),
            tool_registry=self.tool_registry,
            memory_store=self.store,
        )

        loaded = asyncio.run(runtime.resume_task(task.task_id))
        self.assertEqual(loaded.status, TaskStatus.NEEDS_HUMAN)
        self.assertEqual(
            loaded.metadata["human_intervention_reason"],
            "User confirmation required for transfer",
        )


class TestProcessInterruptionAndResumeIntegration(unittest.TestCase):
    """Section 11 End-to-end integration test demonstrating process interruption and resumption."""

    def test_simulate_interruption_and_resume_across_runtimes(self):
        """Integration test steps:
        1. Create task.
        2. Execute part of task.
        3. Persist actions/observations to durable SQLite file.
        4. Simulate process interruption (Runtime 1 dropped).
        5. Re-create Runtime 2 pointing to the same SQLite DB file.
        6. Load task from memory.
        7. Resume task.
        8. Continue adaptive planning.
        9. Verify completion.
        10. Persist COMPLETED.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "durable_memory.db"

            # Shared tools
            tool_reg = ToolRegistry()
            t1 = MockExecutionTool("step_one", "output_step1")
            t2 = MockExecutionTool("step_two", "output_step2")
            tool_reg.register(t1)
            tool_reg.register(t2)

            # --- Phase 1: Runtime 1 initiates task and executes step 1 ---
            store_1 = SQLiteMemoryStore(db_path)
            llm_1 = SequenceMockLLM(
                initial_plan={
                    "goal": "Two-phase workflow",
                    "is_feasible": True,
                    "actions": [{"tool_name": "step_one", "arguments": {"val": 100}}],
                },
                step_responses=[],
            )
            runtime_1 = AgentRuntime(
                llm_provider=llm_1,
                tool_registry=tool_reg,
                memory_store=store_1,
                max_dynamic_steps=1,  # Force pause after step 1 to simulate interruption
            )

            task = Task(user_goal="Process invoice workflow with interruption")
            task_id = task.task_id

            # Execute step 1
            asyncio.run(runtime_1.execute_task(task))
            store_1.close()

            # Verify step 1 recorded in DB
            verify_store = SQLiteMemoryStore(db_path)
            record_interrupted = verify_store.get_task(task_id)
            self.assertIsNotNone(record_interrupted)
            self.assertEqual(len(record_interrupted.actions), 1)
            self.assertEqual(record_interrupted.actions[0].tool_name, "step_one")
            self.assertEqual(len(record_interrupted.observations), 1)
            verify_store.close()

            # --- Phase 2: Simulate process crash/restart ---
            # Create a completely fresh store and runtime instance
            store_2 = SQLiteMemoryStore(db_path)
            llm_2 = SequenceMockLLM(
                initial_plan={},
                step_responses=[
                    {
                        "is_complete": False,
                        "action": {"tool_name": "step_two", "arguments": {"val": 200}},
                        "reasoning": "Step one was already completed, executing step two.",
                    },
                    {
                        "is_complete": True,
                        "completion_summary": "Workflow completed after resumption.",
                        "action": None,
                    },
                ],
            )
            runtime_2 = AgentRuntime(
                llm_provider=llm_2,
                tool_registry=tool_reg,
                memory_store=store_2,
                max_dynamic_steps=5,
            )

            # Mark task back to RUNNING if the prior budget step marked it FAILED/interrupted
            store_2.update_task_state(task_id, state=AgentState.ADAPTING, status=TaskStatus.RUNNING)

            # Resume task
            resumed_task = asyncio.run(runtime_2.resume_task(task_id))

            # Verify successful completion
            self.assertEqual(resumed_task.status, TaskStatus.COMPLETED)
            self.assertEqual(runtime_2.state, AgentState.COMPLETED)

            # Check durable store
            final_record = store_2.get_task(task_id)
            self.assertEqual(final_record.task.status, TaskStatus.COMPLETED)
            self.assertEqual(final_record.state, AgentState.COMPLETED)
            self.assertEqual(len(final_record.actions), 2)
            self.assertEqual(len(final_record.observations), 2)
            self.assertEqual(final_record.actions[0].tool_name, "step_one")
            self.assertEqual(final_record.actions[1].tool_name, "step_two")
            store_2.close()


if __name__ == "__main__":
    unittest.main()
