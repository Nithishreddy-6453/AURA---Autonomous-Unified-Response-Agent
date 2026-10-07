from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CreateTaskRequest(BaseModel):
    user_goal: str = Field(..., min_length=1, description="Goal for AURA to achieve.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional extra metadata.")


class ApprovalRequest(BaseModel):
    feedback: Optional[str] = Field(default=None, description="Optional feedback from human operator.")


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Reason for rejection.")


class TaskSummary(BaseModel):
    task_id: str
    user_goal: str
    status: str
    state: str
    created_at: str
    updated_at: str


class TaskEvent(BaseModel):
    task_id: str
    event_type: str
    message: str
    timestamp: str
    details: Dict[str, Any] = Field(default_factory=dict)


class TaskDetail(BaseModel):
    task_id: str
    user_goal: str
    status: str
    state: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    recovery_events: List[Dict[str, Any]] = Field(default_factory=list)
    policy_events: List[Dict[str, Any]] = Field(default_factory=list)
    plan: Optional[Dict[str, Any]] = None
