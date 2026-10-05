import json
import logging
from typing import Optional

from backend.agent.schemas import PlanResponseSchema, PlanningResult
from backend.llm.base import LLMProvider
from backend.models.action import Action
from backend.models.plan import Plan
from backend.models.task import Task
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


PLANNER_SYSTEM_PROMPT = """You are AURA Planner, an autonomous reasoning and task decomposition engine.
Your role is to analyze a user goal and create an executable, ordered sequence of actions using ONLY the provided tools.

STRICT RULES:
1. You may ONLY choose tool names from the provided Available Tools list.
2. You must NOT invent, guess, hallucinate, or alter any tool names.
3. If the user task requires an action or capability for which NO tool is listed, or cannot be achieved with the available tools, set "is_feasible": false and provide an explanation in "unsupported_reason". In that case, "actions" must be empty.
4. Output MUST be strictly valid JSON conforming to the following schema:
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
5. Do not include markdown codeblocks or any additional conversational commentary. Output raw JSON only.
"""


class Planner:
    """Uses LLM to formulate an actionable plan adhering strictly to registered tools."""

    def __init__(self, llm_provider: LLMProvider, tool_registry: ToolRegistry) -> None:
        self.llm = llm_provider
        self.tool_registry = tool_registry

    async def create_plan(self, task: Task) -> PlanningResult:
        """Formulate a Plan for the given Task or return a structured failure."""
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

        # Parse and sanitize response JSON
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

        # Handle unsupported/infeasible task reported by LLM
        if not plan_response.is_feasible:
            reason = plan_response.unsupported_reason or "Required capabilities are not available in tool registry."
            return PlanningResult(
                success=False,
                goal=plan_response.goal,
                error=f"Task infeasible with available tools: {reason}",
            )

        # Strict validation: verify that all chosen tools exist in the registry
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

        # Construct validated Plan
        plan = Plan(
            task_id=task.task_id,
            goal=plan_response.goal or task.user_goal,
            actions=[
                Action(tool_name=a.tool_name, arguments=a.arguments)
                for a in plan_response.actions
            ],
        )

        return PlanningResult(
            success=True,
            plan_id=plan.plan_id,
            goal=plan.goal,
            actions=plan_response.actions,
        )

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
            # Fallback: find first '{' and last '}'
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return None
