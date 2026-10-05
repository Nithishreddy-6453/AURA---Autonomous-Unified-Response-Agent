import logging
from typing import Callable, List, Optional

from backend.agent.planner import Planner
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus
from backend.tools import ToolRegistry, get_default_tool_registry

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

    Supports observation-grounded dynamic reasoning: after each tool execution,
    the observation is captured, saved in execution memory, and provided to the
    planner to resolve dynamic parameters (such as extracted invoice numbers,
    amounts, dates, and form submissions).
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: Optional[ToolRegistry] = None,
        planner: Optional[Planner] = None,
        on_state_change: Optional[Callable[[AgentState, Task], None]] = None,
        on_action: Optional[Callable[[Action], None]] = None,
        on_observation: Optional[Callable[[Action, Observation], None]] = None,
        max_dynamic_steps: int = 15,
    ) -> None:
        self.llm = llm_provider
        self.tool_registry = tool_registry or get_default_tool_registry()
        self.planner = planner or Planner(
            llm_provider=self.llm,
            tool_registry=self.tool_registry,
        )
        self.state: AgentState = AgentState.RECEIVED
        self.on_state_change = on_state_change
        self.on_action = on_action
        self.on_observation = on_observation
        self.max_dynamic_steps = max_dynamic_steps
        self.current_task: Optional[Task] = None
        self.current_plan: Optional[Plan] = None
        self.executed_actions: List[Action] = []
        self.observations: List[Observation] = []

    def set_state(self, new_state: AgentState) -> None:
        """Transitions the runtime state and triggers callback if configured."""
        logger.info(f"State transition: {self.state} -> {new_state}")
        self.state = new_state
        if self.on_state_change and self.current_task:
            self.on_state_change(new_state, self.current_task)

    async def execute_task(self, task: Task, use_dynamic_adaptation: bool = True) -> Task:
        """Runs the orchestrator through the task lifecycle."""
        self.current_task = task
        self.observations.clear()
        self.executed_actions.clear()
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

        # Build initial Plan object
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
        if not use_dynamic_adaptation:
            # Static execution mode
            for action in self.current_plan.actions:
                success = await self._execute_single_action(action, task)
                if not success:
                    return task
        else:
            # Dynamic adaptation mode: Start with the first discovery action from plan,
            # then ground every subsequent action in the actual observations returned.
            initial_actions = self.current_plan.actions[:1] if self.current_plan.actions else []
            for action in initial_actions:
                success = await self._execute_single_action(action, task)
                if not success:
                    return task

            steps_taken = len(initial_actions)
            while steps_taken < self.max_dynamic_steps:
                next_decision = await self.planner.decide_next_action(
                    task=task,
                    action_history=self.executed_actions,
                    observations=self.observations,
                )

                if next_decision.is_complete:
                    logger.info(f"Task completed: {next_decision.completion_summary}")
                    task.metadata["completion_summary"] = next_decision.completion_summary
                    break

                if not next_decision.action:
                    break

                self.set_state(AgentState.ADAPTING)
                next_action = Action(
                    tool_name=next_decision.action.tool_name,
                    arguments=next_decision.action.arguments,
                )
                self.current_plan.actions.append(next_action)

                success = await self._execute_single_action(next_action, task)
                if not success:
                    return task

                steps_taken += 1

        # 4. Verifying / Completion
        self.set_state(AgentState.VERIFYING)
        task.status = TaskStatus.COMPLETED
        self.set_state(AgentState.COMPLETED)
        return task

    async def _execute_single_action(self, action: Action, task: Task) -> bool:
        """Executes a single action, records observation, and manages state transitions."""
        self.set_state(AgentState.EXECUTING)
        action.status = ActionStatus.RUNNING
        if self.on_action:
            self.on_action(action)

        # Reject unknown tools safely before execution
        if not self.tool_registry.has(action.tool_name):
            obs = Observation(
                action_id=action.action_id,
                success=False,
                error=f"Tool '{action.tool_name}' not found in registry.",
            )
            self.observations.append(obs)
            self.executed_actions.append(action)
            action.status = ActionStatus.FAILED
            self.set_state(AgentState.OBSERVING)
            if self.on_observation:
                self.on_observation(action, obs)
            self.set_state(AgentState.ADAPTING)
            self.set_state(AgentState.FAILED)
            task.status = TaskStatus.FAILED
            task.metadata["error"] = obs.error
            return False

        tool = self.tool_registry.get(action.tool_name)

        try:
            observation = await tool.execute(**action.arguments)
        except Exception as e:
            observation = Observation(
                action_id=action.action_id,
                success=False,
                error=f"Tool execution exception: {str(e)}",
            )

        self.observations.append(observation)
        self.executed_actions.append(action)
        self.set_state(AgentState.OBSERVING)
        if self.on_observation:
            self.on_observation(action, observation)

        if observation.success:
            action.status = ActionStatus.SUCCESS
            return True
        else:
            action.status = ActionStatus.FAILED
            self.set_state(AgentState.ADAPTING)
            self.set_state(AgentState.FAILED)
            task.status = TaskStatus.FAILED
            task.metadata["error"] = observation.error
            return False
