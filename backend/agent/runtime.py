import logging
from typing import Callable, List, Optional

from backend.agent.planner import Planner
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentRuntime:
    """AURA Agent Runtime orchestrating the autonomous task execution lifecycle.

    Lifecycle flow:
    RECEIVED
    -> UNDERSTANDING
    -> PLANNING
    -> EXECUTING
    -> OBSERVING
    -> ADAPTING / VERIFYING
    -> COMPLETED / FAILED / WAITING_FOR_HUMAN
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: Optional[ToolRegistry] = None,
        planner: Optional[Planner] = None,
        on_state_change: Optional[Callable[[AgentState, Task], None]] = None,
    ) -> None:
        self.llm = llm_provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.planner = planner or Planner(
            llm_provider=self.llm,
            tool_registry=self.tool_registry,
        )
        self.state: AgentState = AgentState.RECEIVED
        self.on_state_change = on_state_change
        self.current_task: Optional[Task] = None
        self.current_plan: Optional[Plan] = None
        self.observations: List[Observation] = []

    def set_state(self, new_state: AgentState) -> None:
        """Transitions the runtime state and triggers callback if configured."""
        logger.info(f"State transition: {self.state} -> {new_state}")
        self.state = new_state
        if self.on_state_change and self.current_task:
            self.on_state_change(new_state, self.current_task)

    async def execute_task(self, task: Task) -> Task:
        """Runs the orchestrator through the task lifecycle."""
        self.current_task = task
        self.observations.clear()
        self.set_state(AgentState.RECEIVED)

        # 1. Understanding phase
        self.set_state(AgentState.UNDERSTANDING)
        task.status = TaskStatus.RUNNING

        # 2. Planning phase
        self.set_state(AgentState.PLANNING)
        planning_result = await self.planner.create_plan(task)

        if not planning_result.success:
            logger.warning(f"Planning failed: {planning_result.error}")
            task.status = TaskStatus.FAILED
            task.metadata["error"] = planning_result.error
            self.set_state(AgentState.FAILED)
            return task

        # Build Plan object
        self.current_plan = Plan(
            plan_id=planning_result.plan_id or "",
            task_id=task.task_id,
            goal=planning_result.goal or task.user_goal,
            actions=[
                Action(tool_name=a.tool_name, arguments=a.arguments)
                for a in planning_result.actions
            ],
        )

        if not self.current_plan.actions:
            logger.info("Empty plan returned; marking as completed.")
            task.status = TaskStatus.COMPLETED
            self.set_state(AgentState.COMPLETED)
            return task

        # 3. Execution & Observation Loop
        for action in self.current_plan.actions:
            self.set_state(AgentState.EXECUTING)
            action.status = ActionStatus.RUNNING

            # Reject unknown tools safely before execution
            if not self.tool_registry.has(action.tool_name):
                obs = Observation(
                    action_id=action.action_id,
                    success=False,
                    error=f"Tool '{action.tool_name}' not found in registry.",
                )
                self.observations.append(obs)
                action.status = ActionStatus.FAILED
                self.set_state(AgentState.OBSERVING)
                self.set_state(AgentState.ADAPTING)
                self.set_state(AgentState.FAILED)
                task.status = TaskStatus.FAILED
                task.metadata["error"] = obs.error
                return task

            tool = self.tool_registry.get(action.tool_name)

            try:
                # Dispatch execution to tool interface
                observation = await tool.execute(**action.arguments)
            except Exception as e:
                observation = Observation(
                    action_id=action.action_id,
                    success=False,
                    error=f"Tool execution exception: {str(e)}",
                )

            self.observations.append(observation)
            self.set_state(AgentState.OBSERVING)

            if observation.success:
                action.status = ActionStatus.SUCCESS
            else:
                action.status = ActionStatus.FAILED
                # Adapting / Failure handling point
                self.set_state(AgentState.ADAPTING)
                self.set_state(AgentState.FAILED)
                task.status = TaskStatus.FAILED
                task.metadata["error"] = observation.error
                return task

        # 4. Verifying / Completion
        self.set_state(AgentState.VERIFYING)
        task.status = TaskStatus.COMPLETED
        self.set_state(AgentState.COMPLETED)
        return task
