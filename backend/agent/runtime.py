import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from backend.agent.planner import Planner
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.llm.router import get_llm_provider
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus
from backend.tools import ToolRegistry, get_default_tool_registry
from backend.recovery.recovery_manager import RecoveryManager
from backend.verification.verifier import BaseVerifier
from backend.verification.finance_verifier import (
    FinanceInvoiceVerifier,
    LegacyFinanceVerifierAdapter,
)
from backend.verification.registry import VerifierRegistry, get_default_verifier_registry
from backend.memory.base import MemoryStore
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.policy.decision import PolicyDecision
from backend.policy.engine import ActionPolicy, DefaultActionPolicy, compute_action_fingerprint

logger = logging.getLogger(__name__)


def _is_finance_verifier(v: Any) -> bool:
    """Identifies FinanceInvoiceVerifier or a compatible finance verifier adapter."""
    return (
        isinstance(v, (FinanceInvoiceVerifier, LegacyFinanceVerifierAdapter))
        or getattr(v, "source_name", None) == "finance_verifier"
        or getattr(v, "__class__", None).__name__ == "FinanceInvoiceVerifier"
    )


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

    Supports observation-grounded dynamic reasoning, durable task state persistence,
    and centralized pre-execution safety and permission policy enforcement.
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        tool_registry: Optional[ToolRegistry] = None,
        planner: Optional[Planner] = None,
        memory_store: Optional[MemoryStore] = None,
        policy: Optional[ActionPolicy] = None,
        verifier_registry: Optional[VerifierRegistry] = None,
        on_state_change: Optional[Callable[[AgentState, Task], None]] = None,
        on_action: Optional[Callable[[Action], None]] = None,
        on_observation: Optional[Callable[[Action, Observation], None]] = None,
        max_dynamic_steps: int = 15,
    ) -> None:
        self.llm = llm_provider or get_llm_provider()
        self.tool_registry = tool_registry or get_default_tool_registry()
        self.planner = planner or Planner(
            llm_provider=self.llm,
            tool_registry=self.tool_registry,
        )
        self.memory_store: MemoryStore = memory_store or SQLiteMemoryStore()
        self.policy: ActionPolicy = policy or DefaultActionPolicy()
        self.verifier_registry: VerifierRegistry = (
            verifier_registry if verifier_registry is not None else get_default_verifier_registry()
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
        self.recovery_manager = RecoveryManager()
        self._events: List[Dict[str, Any]] = []

    @property
    def finance_verifier(self) -> Optional[Any]:
        """Backward compatibility property returning the registered FinanceInvoiceVerifier

        or compatible Finance-verifier adapter. Returns None if no finance verifier is registered.
        """
        for v in self.verifier_registry.verifiers:
            if isinstance(v, LegacyFinanceVerifierAdapter):
                return v.wrapped
            if _is_finance_verifier(v):
                return v
        return None

    @finance_verifier.setter
    def finance_verifier(self, verifier: Any) -> None:
        """Backward compatibility setter allowing custom/mock verifiers to replace

        the registered finance verifier while preserving any other registered domain verifiers.
        """
        if isinstance(verifier, (FinanceInvoiceVerifier, LegacyFinanceVerifierAdapter)):
            replacement = verifier
        else:
            replacement = LegacyFinanceVerifierAdapter(verifier)

        replaced = self.verifier_registry.replace_verifier(replacement, _is_finance_verifier)
        if not replaced:
            self.verifier_registry.register(replacement)




    def _record_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records an operational lifecycle event without exposing private reasoning."""
        event = {
            "task_id": task_id,
            "event_type": event_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }
        self._events.append(event)

    def set_state(self, new_state: AgentState, status: Optional[TaskStatus] = None) -> None:
        """Transitions the runtime state, logs memory change, and updates MemoryStore."""
        logger.info(f"State transition: {self.state} -> {new_state}")
        logger.info(f"[MEMORY] state -> {new_state.value}")
        old_state = self.state
        self.state = new_state
        if status is not None and self.current_task:
            self.current_task.status = status
        if self.current_task:
            self.memory_store.update_task_state(
                self.current_task.task_id,
                new_state,
                status=self.current_task.status,
                metadata=self.current_task.metadata,
            )
            self._record_event(
                self.current_task.task_id,
                "STATE_CHANGE",
                f"State changed to {new_state.value}",
                {"from_state": old_state.value, "to_state": new_state.value},
            )
        if self.on_state_change and self.current_task:
            self.on_state_change(new_state, self.current_task)

    async def execute_task(self, task: Task, use_dynamic_adaptation: bool = True) -> Task:
        """Runs the orchestrator through the adaptive task lifecycle with memory persistence."""
        self.current_task = task
        self.observations.clear()
        self.executed_actions.clear()

        # Persist task creation
        self.memory_store.create_task(task, initial_state=AgentState.RECEIVED)
        logger.info(f"[TASK] created {task.task_id}")
        self._record_event(task.task_id, "TASK_CREATED", "Task created", {"user_goal": task.user_goal})
        self.set_state(AgentState.RECEIVED)

        # 1. Understanding phase
        task.status = TaskStatus.RUNNING
        self.set_state(AgentState.UNDERSTANDING, status=TaskStatus.RUNNING)

        # 2. Planning phase
        self.set_state(AgentState.PLANNING)
        planning_result = await self.planner.create_plan(task)

        if not planning_result.success:
            logger.warning(f"Planning failed: {planning_result.error}")
            task.status = TaskStatus.FAILED
            task.metadata["error"] = planning_result.error
            self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
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
        self.memory_store.save_plan(task.task_id, self.current_plan)

        if not self.current_plan.actions:
            logger.info("Empty plan returned; marking as completed.")
            self.set_state(AgentState.COMPLETED, status=TaskStatus.COMPLETED)
            return task

        # 3. Execution & Observation Loop
        if not use_dynamic_adaptation:
            # Static execution mode
            for action in self.current_plan.actions:
                obs = await self._execute_single_action(action, task)
                if not obs.success:
                    self.set_state(AgentState.ADAPTING)
                    task.status = TaskStatus.FAILED
                    task.metadata["error"] = obs.error
                    self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                    return task
            self.set_state(AgentState.VERIFYING)
            self.set_state(AgentState.COMPLETED, status=TaskStatus.COMPLETED)
            return task
        else:
            # Dynamic adaptive execution mode
            initial_actions = self.current_plan.actions[:1] if self.current_plan.actions else []
            recovery_context: Optional[str] = None
            steps_taken = 0

            # Execute first discovery action from plan if present
            for action in initial_actions:
                tool = self.tool_registry.get(action.tool_name) if self.tool_registry.has(action.tool_name) else None
                decision = self.policy.evaluate(task, action, tool)
                outcome_str = "ALLOWED" if decision.allowed else ("REQUIRES_HUMAN" if decision.requires_human else "BLOCKED")
                logger.info(f"[POLICY] {action.tool_name} → {decision.risk_level.value} → {outcome_str}")
                self.memory_store.append_policy_event(task.task_id, decision.to_dict())

                if decision.requires_human:
                    logger.info(f"[WAITING_FOR_HUMAN] {decision.reason}")
                    fp = compute_action_fingerprint(action.tool_name, action.arguments)
                    task.metadata["pending_action"] = action.model_dump()
                    task.metadata["pending_action_fingerprint"] = fp
                    task.metadata["human_intervention_reason"] = decision.reason
                    self.set_state(AgentState.WAITING_FOR_HUMAN, status=TaskStatus.WAITING_FOR_HUMAN)
                    return task

                if decision.blocked:
                    logger.warning(f"[BLOCKED] Action '{action.tool_name}' blocked by policy: {decision.reason}")
                    action.status = ActionStatus.FAILED
                    self.executed_actions.append(action)
                    self.memory_store.append_action(task.task_id, action)
                    obs = Observation(
                        action_id=action.action_id,
                        success=False,
                        error=f"Action blocked by policy: {decision.reason}",
                    )
                    self.observations.append(obs)
                    self.memory_store.append_observation(task.task_id, obs)
                    steps_taken += 1
                    recovery_context = f"Initial action '{action.tool_name}' blocked by safety policy: {decision.reason}."
                    break

                logger.info(f"[PLAN] Initial action: {action.tool_name} {action.arguments}")
                obs = await self._execute_single_action(action, task)
                steps_taken += 1
                if not obs.success:
                    policy = self.recovery_manager.handle_failure(task, obs.error or "", action.tool_name)
                    self.memory_store.append_recovery_event(task.task_id, {
                        "source": action.tool_name,
                        "policy": policy,
                        "error": obs.error,
                    })
                    logger.info(f"[MEMORY] recovery event persisted")
                    logger.warning(f"[RECOVERY] Failure on initial action. Policy: {policy}")
                    if policy == "ESCALATE":
                        self.set_state(AgentState.ADAPTING)
                        task.status = TaskStatus.FAILED
                        task.metadata["error"] = obs.error
                        self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                        return task
                    else:
                        recovery_context = f"Initial action '{action.tool_name}' failed: {obs.error}. Policy: {policy}."

            return await self._run_adaptive_loop(task, recovery_context=recovery_context, steps_taken=steps_taken)

    def approve_task(self, task_id: str, feedback: Optional[str] = None) -> Task:
        """Approves a pending action on a task in WAITING_FOR_HUMAN or NEEDS_HUMAN state."""
        record = self.memory_store.get_task(task_id)
        if not record:
            raise KeyError(f"Task '{task_id}' not found in memory store.")

        task = record.task
        logger.info(f"[APPROVAL] Task {task_id} approved by human operator.")
        task.metadata["approval_status"] = "APPROVED"
        pending_act = task.metadata.get("pending_action")
        if pending_act:
            tool_name = pending_act.get("tool_name", "")
            args = pending_act.get("arguments", {})
            fp = compute_action_fingerprint(tool_name, args)
            task.metadata["approved_action_id"] = pending_act.get("action_id")
            task.metadata["approved_tool_name"] = tool_name
            task.metadata["approved_action_fingerprint"] = fp
            logger.info(f"[APPROVAL] fingerprint={fp}")
        if feedback:
            task.metadata["approval_feedback"] = feedback
        task.status = TaskStatus.RUNNING

        approval_event = {
            "type": "HUMAN_APPROVAL",
            "task_id": task_id,
            "status": "APPROVED",
            "pending_action": pending_act,
            "feedback": feedback,
        }
        self.memory_store.append_policy_event(task_id, approval_event)
        self.memory_store.update_task_state(
            task_id,
            state=AgentState.ADAPTING,
            status=TaskStatus.RUNNING,
            metadata=task.metadata,
        )
        self._record_event(
            task_id,
            "APPROVAL_GRANTED",
            f"Human approved action: {task.metadata.get('approved_tool_name') or 'action'}",
            {"feedback": feedback},
        )
        return task

    def reject_task(self, task_id: str, reason: Optional[str] = None) -> Task:
        """Rejects a pending action on a task in WAITING_FOR_HUMAN or NEEDS_HUMAN state."""
        record = self.memory_store.get_task(task_id)
        if not record:
            raise KeyError(f"Task '{task_id}' not found in memory store.")

        task = record.task
        logger.info(f"[APPROVAL] Task {task_id} rejected by human operator.")
        task.metadata["approval_status"] = "REJECTED"
        if reason:
            task.metadata["rejection_reason"] = reason
        task.status = TaskStatus.FAILED

        reject_event = {
            "type": "HUMAN_REJECTION",
            "task_id": task_id,
            "status": "REJECTED",
            "reason": reason,
        }
        self.memory_store.append_policy_event(task_id, reject_event)
        self.memory_store.update_task_state(
            task_id,
            state=AgentState.FAILED,
            status=TaskStatus.FAILED,
            metadata=task.metadata,
        )
        self._record_event(
            task_id,
            "APPROVAL_REJECTED",
            f"Human rejected action. Reason: {reason or 'No reason provided'}",
            {"reason": reason},
        )
        return task

    def get_task_events(self, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns bounded structured chronological operational events for a task."""
        events = [e for e in self._events if e.get("task_id") == task_id]
        if events:
            return sorted(events, key=lambda x: x.get("timestamp", ""))[-limit:]

        # Reconstruct from persistent MemoryStore if runtime instance is new
        record = self.memory_store.get_task(task_id)
        if not record:
            return []

        reconstructed: List[Dict[str, Any]] = []
        task = record.task
        reconstructed.append({
            "task_id": task_id,
            "event_type": "TASK_CREATED",
            "message": "Task created",
            "timestamp": task.created_at.isoformat(),
            "details": {"user_goal": task.user_goal},
        })

        for act in record.actions:
            reconstructed.append({
                "task_id": task_id,
                "event_type": "ACTION",
                "message": f"Planner executed {act.tool_name}",
                "timestamp": task.updated_at.isoformat(),
                "details": {"tool_name": act.tool_name, "arguments": act.arguments, "status": act.status.value},
            })

        for obs in record.observations:
            msg = "Observation received" if obs.success else f"Observation error: {obs.error}"
            reconstructed.append({
                "task_id": task_id,
                "event_type": "OBSERVATION",
                "message": msg,
                "timestamp": task.updated_at.isoformat(),
                "details": {"success": obs.success, "error": obs.error, "result": obs.result},
            })

        for pol in record.policy_events:
            p_type = pol.get("type", "POLICY_DECISION")
            reconstructed.append({
                "task_id": task_id,
                "event_type": "POLICY",
                "message": f"Policy event: {p_type}",
                "timestamp": task.updated_at.isoformat(),
                "details": pol,
            })

        for rec in record.recovery_events:
            reconstructed.append({
                "task_id": task_id,
                "event_type": "RECOVERY",
                "message": f"Recovery policy: {rec.get('policy', 'UNKNOWN')}",
                "timestamp": task.updated_at.isoformat(),
                "details": rec,
            })

        reconstructed.append({
            "task_id": task_id,
            "event_type": "STATE_CURRENT",
            "message": f"Current state: {record.state.value} ({task.status.value})",
            "timestamp": task.updated_at.isoformat(),
            "details": {"state": record.state.value, "status": task.status.value},
        })

        return reconstructed[-limit:]

    async def resume_task(self, task_id: str) -> Task:
        """Resumes a previously persisted task from its stored state in MemoryStore."""
        record = self.memory_store.get_task(task_id)
        if not record:
            raise KeyError(f"Task '{task_id}' not found in memory store.")

        logger.info(f"[RESUME] loading task {task_id}")
        task = record.task
        self.current_task = task
        self.state = record.state
        self.current_plan = record.plan
        self.executed_actions = list(record.actions)
        self.observations = list(record.observations)

        is_approved = task.metadata.get("approval_status") == "APPROVED"

        # Terminal tasks must not restart automatically unless approved
        terminal_statuses = (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_FOR_HUMAN,
            TaskStatus.NEEDS_HUMAN,
        )
        terminal_states = (
            AgentState.COMPLETED,
            AgentState.FAILED,
            AgentState.WAITING_FOR_HUMAN,
            AgentState.NEEDS_HUMAN,
        )
        if (task.status in terminal_statuses or record.state in terminal_states) and not is_approved:
            logger.info(
                f"[RESUME] Task {task_id} is in terminal status {task.status} / state {record.state}. Returning existing record."
            )
            return task

        # Non-terminal or approved: transition to ADAPTING and resume execution loop from stored history
        logger.info(
            f"[RESUME] Resuming task {task_id} from {len(self.executed_actions)} stored actions."
        )
        task.status = TaskStatus.RUNNING
        self.set_state(AgentState.ADAPTING, status=TaskStatus.RUNNING)

        # If there is an approved pending action, execute it first
        if task.metadata.get("pending_action") and is_approved:
            pending_action_dict = task.metadata.pop("pending_action")
            pending_action = Action.model_validate(pending_action_dict)
            current_fp = compute_action_fingerprint(pending_action.tool_name, pending_action.arguments)
            approved_fp = task.metadata.get("approved_action_fingerprint")

            if approved_fp and current_fp != approved_fp:
                logger.error(
                    f"[APPROVAL] fingerprint mismatch: expected {approved_fp}, got {current_fp}"
                )
                logger.warning("[APPROVAL] authorization invalidated")
                task.metadata["approval_status"] = "INVALIDATED"
                task.metadata.pop("approved_action_fingerprint", None)
                task.metadata["error"] = "Approved action fingerprint mismatch. Action arguments were altered."
                self.memory_store.update_task_state(
                    task_id, state=AgentState.FAILED, status=TaskStatus.FAILED, metadata=task.metadata
                )
                self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                return task

            logger.info(
                f"[RESUME] Executing approved pending action '{pending_action.tool_name}' (fingerprint={current_fp})"
            )
            obs = await self._execute_single_action(pending_action, task)
            recovery_context = None
            if not obs.success:
                policy = self.recovery_manager.handle_failure(task, obs.error or "", pending_action.tool_name)
                recovery_context = f"Approved action '{pending_action.tool_name}' failed: {obs.error}. Policy: {policy}."

            return await self._run_adaptive_loop(
                task, recovery_context=recovery_context, steps_taken=len(self.executed_actions)
            )

        recovery_context = None
        if self.observations and not self.observations[-1].success:
            last_err = self.observations[-1].error or "Previous step failed"
            recovery_context = f"Resumed after failure on previous action: {last_err}."

        return await self._run_adaptive_loop(
            task, recovery_context=recovery_context, steps_taken=len(self.executed_actions)
        )

    async def _run_adaptive_loop(
        self,
        task: Task,
        recovery_context: Optional[str] = None,
        steps_taken: int = 0,
    ) -> Task:
        """Core adaptive execution loop driven by observations and bounded short-term memory."""
        while steps_taken < self.max_dynamic_steps:
            try:
                next_decision = await self.planner.decide_next_action(
                    task=task,
                    action_history=self.executed_actions,
                    observations=self.observations,
                    recovery_context=recovery_context,
                )
            except Exception as e:
                logger.error(f"[PLANNER ERROR] decide_next_action exception: {e}")
                policy = self.recovery_manager.handle_failure(task, str(e), "planner")
                self.memory_store.append_recovery_event(task.task_id, {
                    "source": "planner",
                    "policy": policy,
                    "error": str(e),
                })
                logger.info(f"[RECOVERY] Failure classified for 'planner'. Policy: {policy}")
                if policy == "ESCALATE":
                    logger.warning(f"[ESCALATE] Unrecoverable planner failure: {e}")
                    task.status = TaskStatus.FAILED
                    task.metadata["error"] = f"Planner exception: {e}"
                    self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                    return task
                else:
                    recovery_context = f"Planner exception: {e}. Policy: {policy}. Please produce a valid action or declare completion."
                    steps_taken += 1
                    continue

            # Check if human intervention requested
            if next_decision.needs_human:
                logger.info(f"[NEEDS_HUMAN] {next_decision.reasoning}")
                self.set_state(AgentState.ADAPTING)
                task.status = TaskStatus.NEEDS_HUMAN
                task.metadata["human_intervention_reason"] = next_decision.reasoning
                self.set_state(AgentState.NEEDS_HUMAN, status=TaskStatus.NEEDS_HUMAN)
                return task

            # Check if task completion proposed by planner
            if next_decision.is_complete:
                logger.info(f"[PLAN] Completion proposed: {next_decision.completion_summary}")
                task.metadata["completion_summary"] = next_decision.completion_summary
                self.set_state(AgentState.VERIFYING)

                # Independent Verification against source of truth
                source_ref = (
                    task.metadata.get("source_document")
                    or task.metadata.get("source_file")
                    or task.metadata.get("source_reference")
                )
                if not source_ref:
                    for act in self.executed_actions:
                        if act.tool_name in ("read_company_file", "document_extract"):
                            fp = act.arguments.get("file_path", "")
                            if fp and ("invoice" in fp.lower() or fp.endswith(".txt")):
                                source_ref = fp
                                task.metadata["source_document"] = fp
                                break

                verifier = self.verifier_registry.get_verifier(task)
                if verifier is not None:
                    verifier_source = getattr(verifier, "source_name", verifier.__class__.__name__)
                    verification_result = await verifier.verify(task.metadata, source_reference=source_ref)
                    if not verification_result.is_verified:
                        logger.warning(f"[VERIFY] Verification failed: {verification_result.details}")
                        policy = self.recovery_manager.handle_failure(task, verification_result.details, verifier_source)
                        self.memory_store.append_recovery_event(task.task_id, {
                            "source": verifier_source,
                            "policy": policy,
                            "details": verification_result.details,
                        })
                        logger.info(f"[MEMORY] recovery event persisted")
                        if policy == "ESCALATE":
                            self.set_state(AgentState.ADAPTING)
                            task.status = TaskStatus.FAILED
                            task.metadata["error"] = verification_result.details
                            self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                            return task
                        elif policy == "CORRECT_DATA":
                            logger.info("[ADAPT] Recovering from verification failure by correcting data...")
                            self.set_state(AgentState.ADAPTING)
                            obs = Observation(
                                action_id="verifier",
                                success=False,
                                error=f"Verification failed against source truth: {verification_result.details}. Please correct the data before saving again.",
                            )
                            self.observations.append(obs)
                            self.memory_store.append_observation(task.task_id, obs)
                            logger.info(f"[MEMORY] observation persisted")
                            recovery_context = f"Verification failed against source truth: {verification_result.details}. Policy: CORRECT_DATA."
                            steps_taken += 1
                            continue


                logger.info("[COMPLETE] Task successfully verified and completed.")
                self.set_state(AgentState.COMPLETED, status=TaskStatus.COMPLETED)
                return task

            # If no action is proposed and not explicitly complete, this is a planner failure!
            if not next_decision.action:
                err_msg = next_decision.reasoning or "Planner failed to produce a valid next action or completion decision."
                logger.error(f"[PLANNER ERROR] {err_msg}")
                policy = self.recovery_manager.handle_failure(task, err_msg, "planner")
                self.memory_store.append_recovery_event(task.task_id, {
                    "source": "planner",
                    "policy": policy,
                    "error": err_msg,
                })
                logger.info(f"[RECOVERY] Failure classified for 'planner'. Policy: {policy}")
                if policy == "ESCALATE":
                    logger.warning(f"[ESCALATE] Unrecoverable planner failure: {err_msg}")
                    self.set_state(AgentState.ADAPTING)
                    task.status = TaskStatus.FAILED
                    task.metadata["error"] = err_msg
                    self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                    return task
                else:
                    recovery_context = f"Planner failure: {err_msg}. Policy: {policy}. Please produce a valid registered action or declare completion."
                    steps_taken += 1
                    continue

            # Prepare next action
            next_action = Action(
                tool_name=next_decision.action.tool_name,
                arguments=next_decision.action.arguments,
            )
            if self.current_plan:
                self.current_plan.actions.append(next_action)
                self.memory_store.save_plan(task.task_id, self.current_plan)

            # Duplicate Action Loop Protection
            if len(self.executed_actions) >= 1 and self.observations and not self.observations[-1].success:
                last_act = self.executed_actions[-1]
                if (
                    next_action.tool_name == last_act.tool_name
                    and next_action.arguments == last_act.arguments
                ):
                    next_action.retry_count = last_act.retry_count + 1
                    logger.warning(
                        f"[DUPLICATE BLOCKED] Repeating failed action '{next_action.tool_name}' "
                        f"(attempt {next_action.retry_count + 1})."
                    )
                    if next_action.retry_count >= 2:
                        logger.error("[ESCALATE] Duplicate action loop detected. Escalating.")
                        self.set_state(AgentState.ADAPTING)
                        task.status = TaskStatus.FAILED
                        task.metadata["error"] = f"Loop detected: Repeated failed action '{next_action.tool_name}' without adaptation."
                        self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                        return task

            # Policy evaluation
            tool = self.tool_registry.get(next_action.tool_name) if self.tool_registry.has(next_action.tool_name) else None
            decision = self.policy.evaluate(task, next_action, tool)
            outcome_str = "ALLOWED" if decision.allowed else ("REQUIRES_HUMAN" if decision.requires_human else "BLOCKED")
            logger.info(f"[POLICY] {next_action.tool_name} → {decision.risk_level.value} → {outcome_str}")
            self.memory_store.append_policy_event(task.task_id, decision.to_dict())

            if decision.requires_human:
                logger.info(f"[WAITING_FOR_HUMAN] {decision.reason}")
                fp = compute_action_fingerprint(next_action.tool_name, next_action.arguments)
                task.metadata["pending_action"] = next_action.model_dump()
                task.metadata["pending_action_fingerprint"] = fp
                task.metadata["human_intervention_reason"] = decision.reason
                self.set_state(AgentState.WAITING_FOR_HUMAN, status=TaskStatus.WAITING_FOR_HUMAN)
                return task

            if decision.blocked:
                logger.warning(f"[BLOCKED] Action '{next_action.tool_name}' blocked by policy: {decision.reason}")
                next_action.status = ActionStatus.FAILED
                self.executed_actions.append(next_action)
                self.memory_store.append_action(task.task_id, next_action)
                obs = Observation(
                    action_id=next_action.action_id,
                    success=False,
                    error=f"Action blocked by policy: {decision.reason}",
                )
                self.observations.append(obs)
                self.memory_store.append_observation(task.task_id, obs)
                steps_taken += 1
                recovery_context = f"Action '{next_action.tool_name}' blocked by safety policy: {decision.reason}. Please select an alternative action."
                continue

            logger.info(f"[PLAN] {next_action.tool_name} {next_action.arguments}")
            if next_decision.reasoning:
                logger.info(f"[ADAPT] Reason: {next_decision.reasoning}")

            self.set_state(AgentState.ADAPTING)
            obs = await self._execute_single_action(next_action, task)
            steps_taken += 1

            if not obs.success:
                policy = self.recovery_manager.handle_failure(task, obs.error or "", next_action.tool_name)
                self.memory_store.append_recovery_event(task.task_id, {
                    "source": next_action.tool_name,
                    "policy": policy,
                    "error": obs.error,
                })
                logger.info(f"[MEMORY] recovery event persisted")
                logger.info(f"[RECOVERY] Failure classified for '{next_action.tool_name}'. Policy: {policy}")
                if policy == "ESCALATE":
                    logger.warning(f"[ESCALATE] Unrecoverable failure or retry budget exceeded: {obs.error}")
                    self.set_state(AgentState.ADAPTING)
                    task.status = TaskStatus.FAILED
                    task.metadata["error"] = obs.error
                    self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
                    return task
                else:
                    recovery_context = (
                        f"Action '{next_action.tool_name}' failed: '{obs.error}'. "
                        f"Recovery policy: {policy}. Choose a corrective action."
                    )
            else:
                recovery_context = None

        # Check if step budget was exhausted
        if steps_taken >= self.max_dynamic_steps:
            logger.error(f"[BUDGET EXHAUSTED] Maximum step budget ({self.max_dynamic_steps}) reached.")
            self.set_state(AgentState.ADAPTING)
            task.status = TaskStatus.FAILED
            task.metadata["error"] = f"Execution step budget of {self.max_dynamic_steps} steps exhausted."
            self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
            return task

        # Loop terminated without explicit completion: must NEVER be marked COMPLETED
        logger.error("[FAILED] Planner did not produce a valid completion decision.")
        task.status = TaskStatus.FAILED
        task.metadata["error"] = "Planner did not produce a valid completion decision."
        self.set_state(AgentState.FAILED, status=TaskStatus.FAILED)
        return task

    def _extract_data_from_actions(self) -> Dict[str, Any]:
        """Extracts field data from recent browser actions for independent verification."""
        extracted = {}
        for action in self.executed_actions:
            if action.tool_name == "browser_type":
                args = action.arguments
                selector = args.get("selector", "") or args.get("target", "")
                text = args.get("text", "")
                if "invoice_date" in selector:
                    extracted["invoice_date"] = text
                if "due_date" in selector:
                    extracted["due_date"] = text
                if "amount" in selector:
                    extracted["amount"] = text
                if "company" in selector:
                    extracted["company"] = text
                if "invoice_id" in selector:
                    extracted["invoice_id"] = text
        return extracted

    async def _execute_single_action(self, action: Action, task: Task) -> Observation:
        """Executes a single action, records observation, and manages state transitions."""
        logger.info(f"[EXECUTE] {action.tool_name}")
        self.set_state(AgentState.EXECUTING)
        action.status = ActionStatus.RUNNING
        if self.on_action:
            self.on_action(action)

        self.memory_store.append_action(task.task_id, action)
        logger.info(f"[MEMORY] action persisted")
        self._record_event(
            task.task_id,
            "ACTION_STARTED",
            f"Planner selected {action.tool_name}",
            {"tool_name": action.tool_name, "arguments": action.arguments},
        )

        # Defense-in-depth: check policy as execution gate
        tool = self.tool_registry.get(action.tool_name) if self.tool_registry.has(action.tool_name) else None
        decision = self.policy.evaluate(task, action, tool)
        if decision.blocked:
            obs = Observation(
                action_id=action.action_id,
                success=False,
                error=f"Action blocked by policy: {decision.reason}",
            )
            self.observations.append(obs)
            self.executed_actions.append(action)
            action.status = ActionStatus.FAILED
            self.set_state(AgentState.OBSERVING)
            if self.on_observation:
                self.on_observation(action, obs)
            self.memory_store.append_observation(task.task_id, obs)
            logger.info(f"[MEMORY] observation persisted")
            self.memory_store.append_action(task.task_id, action)
            logger.warning(f"[OBSERVE] Action blocked by policy: {action.tool_name}")
            return obs

        action_fp = compute_action_fingerprint(action.tool_name, action.arguments)
        approved_fp = task.metadata.get("approved_action_fingerprint")
        is_approved = bool(
            task.metadata.get("approval_status") == "APPROVED"
            and (
                (approved_fp and approved_fp == action_fp)
                or (
                    not approved_fp
                    and (
                        task.metadata.get("approved_action_id") == action.action_id
                        or task.metadata.get("approved_tool_name") == action.tool_name
                    )
                )
            )
        )
        if decision.requires_human and not is_approved:
            obs = Observation(
                action_id=action.action_id,
                success=False,
                error=f"Action requires human approval: {decision.reason}",
            )
            self.observations.append(obs)
            self.executed_actions.append(action)
            action.status = ActionStatus.FAILED
            self.set_state(AgentState.OBSERVING)
            if self.on_observation:
                self.on_observation(action, obs)
            self.memory_store.append_observation(task.task_id, obs)
            logger.info(f"[MEMORY] observation persisted")
            self.memory_store.append_action(task.task_id, action)
            logger.warning(f"[OBSERVE] Action requires human approval: {action.tool_name}")
            return obs

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
            self.memory_store.append_observation(task.task_id, obs)
            logger.info(f"[MEMORY] observation persisted")
            self.memory_store.append_action(task.task_id, action)
            logger.warning(f"[OBSERVE] Tool not registered: {action.tool_name}")
            return obs

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

        self.memory_store.append_observation(task.task_id, observation)
        logger.info(f"[MEMORY] observation persisted")

        if observation.success:
            action.status = ActionStatus.SUCCESS
            logger.info(f"[OBSERVE] Success: {action.tool_name}")
            # Single-use consumption of approval authorization
            if approved_fp and approved_fp == action_fp:
                task.metadata.pop("approved_action_fingerprint", None)
                task.metadata["approval_consumed"] = True
                self.memory_store.update_task_state(task.task_id, state=self.state, metadata=task.metadata)
            # Track source document for independent verification
            if action.tool_name in ("read_company_file", "document_extract"):
                fp = action.arguments.get("file_path")
                if fp:
                    task.metadata["source_document"] = fp
                    self.memory_store.update_task_state(task.task_id, state=self.state, metadata=task.metadata)

            self._record_event(
                task.task_id,
                "ACTION_SUCCESS",
                f"{action.tool_name} executed successfully",
                {"tool_name": action.tool_name, "result": observation.result},
            )
        else:
            action.status = ActionStatus.FAILED
            logger.warning(f"[OBSERVE] Failure: {action.tool_name} -> {observation.error}")
            self._record_event(
                task.task_id,
                "ACTION_FAILURE",
                f"{action.tool_name} failed: {observation.error}",
                {"tool_name": action.tool_name, "error": observation.error},
            )

        self.memory_store.append_action(task.task_id, action)
        return observation
