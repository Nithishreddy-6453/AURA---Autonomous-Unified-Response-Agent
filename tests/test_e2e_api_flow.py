import asyncio
import time
import unittest
from unittest.mock import AsyncMock

from backend.agent.schemas import NextActionResponseSchema, PlanActionSchema, PlanningResult
from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.api.main import app, runtime_manager
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.policy.engine import ActionPolicy
from backend.policy.decision import PolicyDecision
from backend.policy.risk import ActionRisk
from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry
from fastapi.testclient import TestClient


class MockWireTool(Tool):
    @property
    def name(self) -> str:
        return "sensitive_wire_transfer"

    @property
    def description(self) -> str:
        return "Initiates sensitive wire transfer."

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    async def execute(self, **kwargs):
        return Observation(action_id="wire", success=True, result={"status": "sent"})


class TestE2EApiFlow(unittest.TestCase):
    """End-to-End API test verifying task creation, polling, approval, and completion."""

    def setUp(self):
        self._orig_get_runtime = runtime_manager.get_runtime_for_task
        self.mem_store = SQLiteMemoryStore(":memory:")
        runtime_manager.memory_store = self.mem_store
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()
        self.client = TestClient(app)

    def tearDown(self):
        self.mem_store.close()
        runtime_manager.get_runtime_for_task = self._orig_get_runtime
        runtime_manager.memory_store = SQLiteMemoryStore()
        runtime_manager.runtimes.clear()

    def test_human_approval_lifecycle_via_api(self):
        """Tests: POST /api/tasks -> WAITING_FOR_HUMAN -> POST /api/tasks/{id}/approve -> COMPLETED."""
        # Setup custom policy requiring approval
        class ApprovalRequiredPolicy(ActionPolicy):
            def evaluate(self, task, action, tool=None):
                if action.tool_name == "sensitive_wire_transfer":
                    return PolicyDecision(
                        allowed=False,
                        requires_human=True,
                        blocked=False,
                        risk_level=ActionRisk.SENSITIVE,
                        reason="Wire transfer requires supervisor authorization.",
                    )
                return PolicyDecision(
                    allowed=True,
                    requires_human=False,
                    blocked=False,
                    risk_level=ActionRisk.READ,
                    reason="Read allowed.",
                )

        tool_reg = ToolRegistry()
        tool_reg.register(MockWireTool())

        runtime = AgentRuntime(
            memory_store=self.mem_store,
            policy=ApprovalRequiredPolicy(),
            tool_registry=tool_reg,
        )

        wire_act = PlanActionSchema(tool_name="sensitive_wire_transfer", arguments={"amount": 5000})
        runtime.planner.create_plan = AsyncMock(
            return_value=PlanningResult(
                success=True,
                goal="Transfer 5000 USD to supplier.",
                actions=[wire_act],
            )
        )

        decisions = [
            NextActionResponseSchema(
                is_complete=True,
                completion_summary="Transfer completed and verified.",
            ),
        ]
        decision_idx = 0

        async def mock_decide_next_action(*args, **kwargs):
            nonlocal decision_idx
            d = decisions[min(decision_idx, len(decisions) - 1)]
            decision_idx += 1
            return d

        runtime.planner.decide_next_action = AsyncMock(side_effect=mock_decide_next_action)

        # Ensure runtime_manager uses our prepared runtime
        runtime_manager.get_runtime_for_task = lambda tid: runtime

        # 1. Create Task via API
        resp = self.client.post(
            "/api/tasks",
            json={"user_goal": "Transfer 5000 USD to supplier."},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        task_id = data["task_id"]

        # Wait for background task to pause at WAITING_FOR_HUMAN
        if task_id in runtime_manager.background_tasks:
            bg = runtime_manager.background_tasks[task_id]
            timeout = time.time() + 5.0
            while not bg.done() and time.time() < timeout:
                time.sleep(0.05)

        # 2. Poll Task Details via API
        detail_resp = self.client.get(f"/api/tasks/{task_id}")
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertEqual(detail["state"], AgentState.WAITING_FOR_HUMAN.value)
        self.assertEqual(detail["status"], TaskStatus.WAITING_FOR_HUMAN.value)
        self.assertIn("pending_action", detail["metadata"])
        self.assertEqual(
            detail["metadata"]["pending_action"]["tool_name"],
            "sensitive_wire_transfer",
        )

        # 3. Verify Events endpoint shows WAITING_FOR_HUMAN / POLICY events
        events_resp = self.client.get(f"/api/tasks/{task_id}/events")
        self.assertEqual(events_resp.status_code, 200)
        events = events_resp.json()
        self.assertTrue(len(events) >= 2)

        # 4. Human Approves via API
        approve_resp = self.client.post(
            f"/api/tasks/{task_id}/approve",
            json={"feedback": "Approved by Finance Director."},
        )
        self.assertEqual(approve_resp.status_code, 200)

        # Wait for resume background task
        if task_id in runtime_manager.background_tasks:
            bg = runtime_manager.background_tasks[task_id]
            timeout = time.time() + 5.0
            while not bg.done() and time.time() < timeout:
                time.sleep(0.05)

        # 5. Verify final status is COMPLETED
        final_resp = self.client.get(f"/api/tasks/{task_id}")
        final_detail = final_resp.json()
        self.assertEqual(final_detail["state"], AgentState.COMPLETED.value)
        self.assertEqual(final_detail["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(
            final_detail["metadata"].get("approval_status"),
            "APPROVED",
        )
        print("\n[PASS] End-to-end API lifecycle test: Created -> Waiting_For_Human -> Approved -> Completed.")


if __name__ == "__main__":
    unittest.main()
