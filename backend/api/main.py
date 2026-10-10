import asyncio
import logging
import os
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.api.models import (
    ApprovalRequest,
    CreateTaskRequest,
    RejectRequest,
    TaskDetail,
    TaskEvent,
    TaskSummary,
)
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_ORIGINS: List[str] = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]


def get_allowed_origins() -> List[str]:
    """Retrieves and parses allowed frontend origins from environment or defaults."""
    env_origins = os.getenv("AURA_ALLOWED_ORIGINS") or os.getenv("ALLOWED_ORIGINS")
    if not env_origins:
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins = [orig.strip() for orig in env_origins.split(",") if orig.strip()]
    return origins if origins else list(DEFAULT_ALLOWED_ORIGINS)


app = FastAPI(
    title="AURA Agent API",
    description="Autonomous Unified Response Agent API and Control Center Gateway",
    version="0.5.0",
)

# CORS configuration for Control Center and Finance Portal
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RuntimeManager:
    """Manages AgentRuntime instances and background execution for API tasks."""

    def __init__(self, memory_store: Optional[SQLiteMemoryStore] = None) -> None:
        self.memory_store = memory_store or SQLiteMemoryStore()
        self.runtimes: Dict[str, AgentRuntime] = {}
        self.background_tasks: Dict[str, asyncio.Task] = {}

    def get_runtime_for_task(self, task_id: str) -> AgentRuntime:
        if task_id not in self.runtimes:
            runtime = AgentRuntime(
                memory_store=self.memory_store,
            )
            self.runtimes[task_id] = runtime
        return self.runtimes[task_id]


runtime_manager = RuntimeManager()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "service": "aura-agent-api"},
    )


@app.post("/api/tasks", response_model=TaskSummary, status_code=status.HTTP_201_CREATED)
async def create_task(request: CreateTaskRequest):
    """Creates a new autonomous task and launches execution in the background."""
    goal = request.user_goal.strip()
    if not goal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User goal cannot be empty.",
        )

    task = Task(user_goal=goal, metadata=request.metadata or {})
    runtime = runtime_manager.get_runtime_for_task(task.task_id)

    # Immediately persist initial record so queries never race
    runtime.memory_store.create_task(task, initial_state=AgentState.RECEIVED)
    runtime._record_event(
        task.task_id,
        "TASK_CREATED",
        "Task created",
        {"user_goal": task.user_goal},
    )

    async def _run():
        try:
            await runtime.execute_task(task)
        except Exception as e:
            logger.exception(f"Background task execution failed: {e}")
            runtime.set_state(AgentState.FAILED, status=TaskStatus.FAILED)

    bg = asyncio.create_task(_run())
    runtime_manager.background_tasks[task.task_id] = bg

    return TaskSummary(
        task_id=task.task_id,
        user_goal=task.user_goal,
        status=task.status.value,
        state=AgentState.RECEIVED.value,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


@app.get("/api/tasks", response_model=List[TaskSummary])
async def list_tasks(limit: int = Query(default=20, ge=1, le=100)):
    """Lists recent tasks recorded in SQLite MemoryStore."""
    records = runtime_manager.memory_store.list_tasks(limit=limit)
    summaries = []
    for rec in records:
        summaries.append(
            TaskSummary(
                task_id=rec.task.task_id,
                user_goal=rec.task.user_goal,
                status=rec.task.status.value,
                state=rec.state.value,
                created_at=rec.task.created_at.isoformat(),
                updated_at=rec.task.updated_at.isoformat(),
            )
        )
    return summaries


@app.get("/api/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str):
    """Returns complete details of a task from MemoryStore."""
    record = runtime_manager.memory_store.get_task(task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    return TaskDetail(
        task_id=record.task.task_id,
        user_goal=record.task.user_goal,
        status=record.task.status.value,
        state=record.state.value,
        created_at=record.task.created_at.isoformat(),
        updated_at=record.task.updated_at.isoformat(),
        metadata=record.task.metadata,
        actions=[
            {
                "action_id": a.action_id,
                "tool_name": a.tool_name,
                "arguments": a.arguments,
                "status": a.status.value,
                "retry_count": a.retry_count,
            }
            for a in record.actions
        ],
        observations=[
            {
                "action_id": o.action_id,
                "success": o.success,
                "result": o.result,
                "error": o.error,
                "metadata": o.metadata,
            }
            for o in record.observations
        ],
        recovery_events=record.recovery_events,
        policy_events=record.policy_events,
        plan=record.plan.model_dump() if record.plan else None,
    )


@app.get("/api/tasks/{task_id}/events", response_model=List[TaskEvent])
async def get_task_events(task_id: str, limit: int = Query(default=50, ge=1, le=200)):
    """Returns chronological operational events for a task."""
    record = runtime_manager.memory_store.get_task(task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    runtime = runtime_manager.get_runtime_for_task(task_id)
    raw_events = runtime.get_task_events(task_id, limit=limit)
    return [
        TaskEvent(
            task_id=e.get("task_id", task_id),
            event_type=e.get("event_type", "INFO"),
            message=e.get("message", ""),
            timestamp=e.get("timestamp", ""),
            details=e.get("details", {}),
        )
        for e in raw_events
    ]


@app.post("/api/tasks/{task_id}/approve", response_model=TaskSummary)
async def approve_task(task_id: str, request: Optional[ApprovalRequest] = None):
    """Approves a task in WAITING_FOR_HUMAN and resumes execution in the background."""
    record = runtime_manager.memory_store.get_task(task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    runtime = runtime_manager.get_runtime_for_task(task_id)
    feedback = request.feedback if request else None

    try:
        updated_task = runtime.approve_task(task_id, feedback=feedback)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to approve task: {str(e)}",
        )

    async def _resume():
        try:
            await runtime.resume_task(task_id)
        except Exception as e:
            logger.exception(f"Background resume execution failed: {e}")
            runtime.set_state(AgentState.FAILED, status=TaskStatus.FAILED)

    bg = asyncio.create_task(_resume())
    runtime_manager.background_tasks[task_id] = bg

    return TaskSummary(
        task_id=updated_task.task_id,
        user_goal=updated_task.user_goal,
        status=updated_task.status.value,
        state=runtime.state.value,
        created_at=updated_task.created_at.isoformat(),
        updated_at=updated_task.updated_at.isoformat(),
    )


@app.post("/api/tasks/{task_id}/reject", response_model=TaskSummary)
async def reject_task(task_id: str, request: Optional[RejectRequest] = None):
    """Rejects a pending action for a task in WAITING_FOR_HUMAN state."""
    record = runtime_manager.memory_store.get_task(task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    runtime = runtime_manager.get_runtime_for_task(task_id)
    reason = request.reason if request else None

    try:
        updated_task = runtime.reject_task(task_id, reason=reason)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to reject task: {str(e)}",
        )

    return TaskSummary(
        task_id=updated_task.task_id,
        user_goal=updated_task.user_goal,
        status=updated_task.status.value,
        state=AgentState.FAILED.value,
        created_at=updated_task.created_at.isoformat(),
        updated_at=updated_task.updated_at.isoformat(),
    )


@app.post("/api/tasks/{task_id}/resume", response_model=TaskSummary)
async def resume_task(task_id: str):
    """Resumes a paused or interrupted non-terminal task in the background."""
    record = runtime_manager.memory_store.get_task(task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    runtime = runtime_manager.get_runtime_for_task(task_id)

    async def _resume():
        try:
            await runtime.resume_task(task_id)
        except Exception as e:
            logger.exception(f"Background resume execution failed: {e}")
            runtime.set_state(AgentState.FAILED, status=TaskStatus.FAILED)

    bg = asyncio.create_task(_resume())
    runtime_manager.background_tasks[task_id] = bg

    return TaskSummary(
        task_id=record.task.task_id,
        user_goal=record.task.user_goal,
        status=record.task.status.value,
        state=record.state.value,
        created_at=record.task.created_at.isoformat(),
        updated_at=record.task.updated_at.isoformat(),
    )
