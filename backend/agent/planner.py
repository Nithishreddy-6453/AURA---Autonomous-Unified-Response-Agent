import json
import logging
from typing import Any, Dict, List, Optional

from backend.agent.schemas import (
    NextActionResponseSchema,
    PlanActionSchema,
    PlanResponseSchema,
    PlanningResult,
)
from backend.llm.base import LLMProvider
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


PLANNER_SYSTEM_PROMPT = """You are AURA Planner, an autonomous reasoning and task decomposition engine.
Your role is to analyze a user goal and create an initial plan using ONLY the provided tools.

STRICT RULES:
1. You may ONLY choose tool names from the provided Available Tools list.
2. You must NOT invent, guess, hallucinate, or alter any tool names.
3. If information must first be discovered (e.g. searching company files to identify files or navigating to a portal), plan ONLY the initial concrete action (e.g. search_company_files). Do NOT guess future arguments or use template placeholders like '{{...}}'.
4. Every argument in every planned action MUST be an actual, concrete value known right now (e.g. {"query": "Acme invoice", "category": "invoices"}). Never output placeholders or ungrounded filenames.
5. If the user task requires an action or capability for which NO tool is listed, set "is_feasible": false and explain in "unsupported_reason".
6. Output MUST be strictly valid JSON conforming to the following schema:
{
  "goal": "<succinct goal summary>",
  "is_feasible": true|false,
  "unsupported_reason": null | "<explanation if is_feasible is false>",
  "actions": [
    {
      "tool_name": "<exact name from available tools>",
      "arguments": { <parameters according to tool schema> }
    }
  ]
}
7. Do not include markdown codeblocks or any additional conversational commentary. Output raw JSON only.
"""

NEXT_ACTION_SYSTEM_PROMPT = """You are AURA Step Reasoner, an autonomous task execution engine.
Given the User Goal, the Available Tools, and the History of executed Actions and their Observations, determine the single NEXT action to perform.

STRICT RULES:
1. You may ONLY choose tool names from the Available Tools list. Never invent or hallucinate tool names.
2. If the goal has been fully accomplished, set "is_complete": true, provide "completion_summary", and set "action": null.
3. If human intervention is required (e.g. clarification needed, missing credentials, approval required), set "needs_human": true, explain in "reasoning", and set "action": null.
4. If the goal is not yet complete, specify the exact next "action" with "tool_name" and "arguments" adhering to the tool schema.
5. Ground your arguments in the actual observations returned from prior steps:
   - When choosing which invoice file is latest, compare dates and filenames returned in observations.
   - Use the exact extracted invoice ID, date, amount, due date from read_company_file or document_extract observations.
   - For browser navigation, use the allowed portal URL (e.g. 'http://localhost:3000/finance/invoices/new').
   - For browser typing, use valid targets like 'invoice_id', 'company', 'amount', 'due_date', 'invoice_date', etc.
   - For submitting, click the submit button (e.g. text='Save Invoice' or selector='#submit-invoice-button').
   - Take a screenshot as evidence before marking completion.
6. Do NOT repeat failed or identical actions without changing arguments. If a previous action failed with an error, perform the corrective action (such as typing the missing required field or correcting the format).
7. Output MUST be strictly valid JSON conforming to the schema:
{
  "is_complete": true|false,
  "needs_human": true|false,
  "completion_summary": null | "<summary if complete>",
  "reasoning": "<brief operational reasoning for choosing this action based on prior observations>",
  "action": {
    "tool_name": "<tool from available tools>",
    "arguments": { <arguments matching tool schema> }
  }
}
8. Do not include markdown codeblocks or any extra commentary. Output raw JSON only.
"""


class Planner:
    """Uses LLM to formulate an actionable plan and dynamically determine subsequent actions."""

    def __init__(self, llm_provider: LLMProvider, tool_registry: ToolRegistry) -> None:
        self.llm = llm_provider
        self.tool_registry = tool_registry

    async def create_plan(self, task: Task) -> PlanningResult:
        """Formulate an initial Plan for the given Task or return a structured failure."""
        tool_specs = self.tool_registry.get_tool_specs()

        user_content = (
            f"User Goal: {task.user_goal}\n\n"
            f"Available Tools:\n{json.dumps(tool_specs, indent=2)}\n\n"
            f"Formulate the plan as JSON strictly matching the schema."
        )

        try:
            raw_response = await self.llm.generate(
                prompt=user_content,
                system_instruction=PLANNER_SYSTEM_PROMPT,
                temperature=0.0,
            )
        except Exception as e:
            logger.error(f"Planner LLM generation error: {e}")
            return PlanningResult(
                success=False,
                error=f"LLM generation failed: {str(e)}",
            )

        parsed_data = self._parse_json(raw_response)
        if not parsed_data:
            return PlanningResult(
                success=False,
                error=f"Planner received invalid or non-JSON output from LLM: {raw_response}",
            )

        try:
            plan_response = PlanResponseSchema.model_validate(parsed_data)
        except Exception as e:
            return PlanningResult(
                success=False,
                error=f"Plan response did not conform to schema: {str(e)}",
            )

        if not plan_response.is_feasible:
            reason = plan_response.unsupported_reason or "Required capabilities are not available in tool registry."
            return PlanningResult(
                success=False,
                goal=plan_response.goal,
                error=f"Task infeasible with available tools: {reason}",
            )

        validated_actions = []
        for action_spec in plan_response.actions:
            if not self.tool_registry.has(action_spec.tool_name):
                return PlanningResult(
                    success=False,
                    goal=plan_response.goal,
                    error=(
                        f"Planner generated unavailable tool '{action_spec.tool_name}'. "
                        f"Registered tools are: {[t.name for t in self.tool_registry.list_tools()]}"
                    ),
                )
            # If an action uses placeholder templates, drop it from the initial plan so
            # concrete actions execute first and the reasoner provides grounded values later.
            has_placeholder = any(
                isinstance(arg_v, str) and "{{" in arg_v and "}}" in arg_v
                for arg_v in action_spec.arguments.values()
            )
            if not has_placeholder:
                validated_actions.append(action_spec)

        # If all actions had placeholders, fail clearly
        if plan_response.actions and not validated_actions:
            return PlanningResult(
                success=False,
                goal=plan_response.goal,
                error="Initial plan contained only template placeholders without any concrete executable action.",
            )

        plan = Plan(
            task_id=task.task_id,
            goal=plan_response.goal or task.user_goal,
            actions=[
                Action(tool_name=a.tool_name, arguments=a.arguments)
                for a in validated_actions
            ],
        )

        return PlanningResult(
            success=True,
            plan_id=plan.plan_id,
            goal=plan.goal,
            actions=validated_actions,
        )

    async def decide_next_action(
        self,
        task: Task,
        action_history: List[Action],
        observations: List[Observation],
        recovery_context: Optional[str] = None,
        max_recent_history: int = 5,
    ) -> NextActionResponseSchema:
        """Determines the next step dynamically given bounded previous observations and recovery context."""
        tool_specs = self.tool_registry.get_tool_specs()

        # Bounded recent history
        recent_pairs = list(zip(action_history, observations))[-max_recent_history:]
        history_summary = []
        start_step = len(action_history) - len(recent_pairs) + 1
        for i, (act, obs) in enumerate(recent_pairs, start=start_step):
            history_summary.append({
                "step": i,
                "tool": act.tool_name,
                "arguments": act.arguments,
                "success": obs.success,
                "result": obs.result if obs.success else None,
                "error": obs.error if not obs.success else None,
            })

        latest_obs = observations[-1] if observations else None
        latest_obs_summary = {
            "success": latest_obs.success,
            "result": latest_obs.result if latest_obs.success else None,
            "error": latest_obs.error if not latest_obs.success else None,
        } if latest_obs else None

        recovery_section = f"\nRecovery & Error Guidance:\n{recovery_context}\n" if recovery_context else ""

        duplicate_warning = ""
        if action_history and observations and not observations[-1].success:
            last_act = action_history[-1]
            duplicate_warning = (
                f"\nWARNING: Step {len(action_history)} '{last_act.tool_name}' failed. "
                f"Do NOT repeat the exact same tool and arguments without correcting the cause."
            )

        user_content = (
            f"User Goal: {task.user_goal}\n"
            f"Current Task Status: {task.status.value}\n\n"
            f"Available Tools:\n{json.dumps(tool_specs, indent=2)}\n\n"
            f"Execution History & Observations:\n{json.dumps(history_summary, indent=2)}\n\n"
            f"Latest Observation:\n{json.dumps(latest_obs_summary, indent=2)}\n"
            f"{recovery_section}"
            f"{duplicate_warning}\n\n"
            f"Provide the NEXT action, request human intervention, or declare completion as raw JSON."
        )

        try:
            raw_response = await self.llm.generate(
                prompt=user_content,
                system_instruction=NEXT_ACTION_SYSTEM_PROMPT,
                temperature=0.0,
            )
        except Exception as e:
            return NextActionResponseSchema(
                is_complete=False,
                reasoning=f"LLM generation failed: {str(e)}",
            )

        parsed_data = self._parse_json(raw_response)
        if not parsed_data:
            return NextActionResponseSchema(
                is_complete=False,
                reasoning=f"Failed to parse LLM response as JSON: {raw_response}",
            )

        try:
            decision = NextActionResponseSchema.model_validate(parsed_data)
        except Exception as e:
            return NextActionResponseSchema(
                is_complete=False,
                reasoning=f"Schema validation error: {str(e)}",
            )

        # Validate that proposed tool is registered in ToolRegistry
        if decision.action:
            if not self.tool_registry.has(decision.action.tool_name):
                logger.warning(f"Planner proposed unregistered tool '{decision.action.tool_name}'")
                return NextActionResponseSchema(
                    is_complete=False,
                    action=None,
                    reasoning=f"Tool '{decision.action.tool_name}' is not registered in ToolRegistry.",
                )

        return decision

    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract and parse JSON object from raw response text."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return None
