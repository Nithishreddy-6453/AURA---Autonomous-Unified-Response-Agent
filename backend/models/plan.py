from typing import List
from uuid import uuid4
from pydantic import BaseModel, Field

from backend.models.action import Action


class Plan(BaseModel):
    """Represents an ordered plan composed of discrete actions to achieve a goal."""

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    goal: str
    actions: List[Action] = Field(default_factory=list)
