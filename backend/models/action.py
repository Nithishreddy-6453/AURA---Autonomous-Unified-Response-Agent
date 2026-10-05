from enum import Enum
from typing import Any, Dict
from uuid import uuid4
from pydantic import BaseModel, Field


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Action(BaseModel):
    """Represents a discrete step/action to execute a specific tool with arguments."""

    action_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PENDING
    retry_count: int = 0
