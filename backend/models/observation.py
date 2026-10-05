from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class Observation(BaseModel):
    """Represents the observation returned from an environment/tool execution."""

    action_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
