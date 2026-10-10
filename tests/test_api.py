import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from backend.agent.state import AgentState
from backend.api.main import app, runtime_manager
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.action import Action
from backend.models.task import Task, TaskStatus


class TestControlCenterAPI(unittest.TestCase):
    """Unit tests for AURA Control Center FastAPI endpoints."""

    def setUp(self):
        # Use an in-memory database for isolated test runs
        self.mem_store = SQLiteMemoryStore(":memory:")
        runtime_manager.memory_store = self.mem_store
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()
        self.client = TestClient(app)

    def tearDown(self):
        self.mem_store.close()
        runtime_manager.memory_store = SQLiteMemoryStore()
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()

    def test_health_check(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "aura-agent-api")

    def test_create_task_success(self):
        response = self.client.post(
            "/api/tasks",
            json={"user_goal": "Find the latest Acme invoice."},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("task_id", data)
        self.assertEqual(data["user_goal"], "Find the latest Acme invoice.")
        self.assertIn(data["state"], ["RECEIVED", "UNDERSTANDING", "PLANNING", "EXECUTING", "COMPLETED", "FAILED"])

        # Confirm persisted in MemoryStore
        record = self.mem_store.get_task(data["task_id"])
        self.assertIsNotNone(record)
        self.assertEqual(record.task.user_goal, "Find the latest Acme invoice.")

    def test_create_task_empty_goal(self):
        response = self.client.post(
            "/api/tasks",
            json={"user_goal": "   "},
        )
        self.assertEqual(response.status_code, 400)

    def test_list_tasks(self):
        # Create two tasks
        t1 = Task(user_goal="Task 1")
        t2 = Task(user_goal="Task 2")
        self.mem_store.create_task(t1, initial_state=AgentState.COMPLETED)
        self.mem_store.create_task(t2, initial_state=AgentState.RECEIVED)

        response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 2)
        goals = [i["user_goal"] for i in items]
        self.assertIn("Task 1", goals)
        self.assertIn("Task 2", goals)

    def test_get_task_detail(self):
        t = Task(user_goal="Inspect records", metadata={"foo": "bar"})
        self.mem_store.create_task(t, initial_state=AgentState.EXECUTING)
        act = Action(tool_name="search_company_files", arguments={"pattern": "*.pdf"})
        self.mem_store.append_action(t.task_id, act)

        response = self.client.get(f"/api/tasks/{t.task_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["task_id"], t.task_id)
        self.assertEqual(data["user_goal"], "Inspect records")
        self.assertEqual(data["metadata"]["foo"], "bar")
        self.assertEqual(len(data["actions"]), 1)
        self.assertEqual(data["actions"][0]["tool_name"], "search_company_files")

    def test_get_task_not_found(self):
        response = self.client.get("/api/tasks/non-existent-task-id")
        self.assertEqual(response.status_code, 404)

    def test_get_task_events(self):
        t = Task(user_goal="Process invoice")
        self.mem_store.create_task(t, initial_state=AgentState.RECEIVED)
        runtime = runtime_manager.get_runtime_for_task(t.task_id)
        runtime._record_event(t.task_id, "TASK_CREATED", "Task created")
        runtime._record_event(t.task_id, "ACTION_STARTED", "Planner selected search_files")

        response = self.client.get(f"/api/tasks/{t.task_id}/events")
        self.assertEqual(response.status_code, 200)
        events = response.json()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "TASK_CREATED")
        self.assertEqual(events[1]["event_type"], "ACTION_STARTED")

    def test_approve_task(self):
        t = Task(
            user_goal="Approve payment",
            metadata={"pending_action": {"action_id": "act-1", "tool_name": "pay_invoice"}},
        )
        self.mem_store.create_task(t, initial_state=AgentState.WAITING_FOR_HUMAN)
        t.status = TaskStatus.WAITING_FOR_HUMAN
        self.mem_store.update_task_state(
            t.task_id,
            state=AgentState.WAITING_FOR_HUMAN,
            status=TaskStatus.WAITING_FOR_HUMAN,
            metadata=t.metadata,
        )

        response = self.client.post(
            f"/api/tasks/{t.task_id}/approve",
            json={"feedback": "Approved by CFO"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["task_id"], t.task_id)

        # Check that approval status is recorded
        rec = self.mem_store.get_task(t.task_id)
        self.assertEqual(rec.task.metadata.get("approval_status"), "APPROVED")
        self.assertEqual(rec.task.metadata.get("approval_feedback"), "Approved by CFO")

    def test_reject_task(self):
        t = Task(user_goal="Approve payment")
        self.mem_store.create_task(t, initial_state=AgentState.WAITING_FOR_HUMAN)
        t.status = TaskStatus.WAITING_FOR_HUMAN
        self.mem_store.update_task_state(
            t.task_id,
            state=AgentState.WAITING_FOR_HUMAN,
            status=TaskStatus.WAITING_FOR_HUMAN,
        )

        response = self.client.post(
            f"/api/tasks/{t.task_id}/reject",
            json={"reason": "Payment too high"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["state"], "FAILED")

        rec = self.mem_store.get_task(t.task_id)
        self.assertEqual(rec.task.metadata.get("approval_status"), "REJECTED")
        self.assertEqual(rec.state, AgentState.FAILED)

    def test_approve_missing_task(self):
        response = self.client.post(
            "/api/tasks/unknown-task-id/approve",
            json={"feedback": "ok"},
        )
        self.assertEqual(response.status_code, 404)

    def test_resume_task(self):
        t = Task(user_goal="Resume me")
        self.mem_store.create_task(t, initial_state=AgentState.ADAPTING)

        response = self.client.post(f"/api/tasks/{t.task_id}/resume")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["task_id"], t.task_id)


if __name__ == "__main__":
    unittest.main()
