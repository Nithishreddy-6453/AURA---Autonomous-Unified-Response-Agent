from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.agent.state import AgentState
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus


class TaskRecord(BaseModel):
    """Aggregated persistent record representing complete task memory and history."""

    task: Task
    state: AgentState
    actions: List[Action] = Field(default_factory=list)
    observations: List[Observation] = Field(default_factory=list)
    recovery_events: List[Dict[str, Any]] = Field(default_factory=list)
    policy_events: List[Dict[str, Any]] = Field(default_factory=list)
    plan: Optional[Plan] = None


class MemoryStore(ABC):
    """Abstract interface for task state persistence and short-term agent memory.

    Decouples AgentRuntime execution lifecycle from underlying storage engines.
    """

    @abstractmethod
    def create_task(self, task: Task, initial_state: AgentState = AgentState.RECEIVED) -> None:
        """Persists a newly initiated task record."""
        pass

    @abstractmethod
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Loads a task and its full execution history by unique task_id."""
        pass

    @abstractmethod
    def update_task_state(
        self,
        task_id: str,
        state: AgentState,
        status: Optional[TaskStatus] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Updates the current state, status, and metadata of a task."""
        pass

    @abstractmethod
    def append_action(self, task_id: str, action: Action) -> None:
        """Appends an executed action to the task history."""
        pass

    @abstractmethod
    def append_observation(self, task_id: str, observation: Observation) -> None:
        """Appends an observed outcome to the task history."""
        pass

    @abstractmethod
    def append_recovery_event(self, task_id: str, event: Dict[str, Any]) -> None:
        """Appends a failure classification or recovery intervention event."""
        pass

    @abstractmethod
    def append_policy_event(self, task_id: str, event: Dict[str, Any]) -> None:
        """Appends an auditable record of a policy decision or approval event."""
        pass

    @abstractmethod
    def save_plan(self, task_id: str, plan: Plan) -> None:
        """Persists the task plan."""
        pass

    @abstractmethod
    def get_recent_history(
        self, task_id: str, limit: int = 5
    ) -> Tuple[List[Action], List[Observation]]:
        """Retrieves bounded recent actions and observations for planner reasoning."""
        pass

    @abstractmethod
    def list_tasks(self, limit: int = 20) -> List[TaskRecord]:
        """Lists recent tasks across the system."""
        pass
