import logging
from typing import Optional
from backend.recovery.classifier import classify_failure, FailureType
from backend.recovery.policies import get_recovery_policy
from backend.models.task import Task

logger = logging.getLogger(__name__)

class RecoveryManager:
    def __init__(self):
        self.retry_counts = {} # task_id -> count

    def handle_failure(self, task: Task, error_msg: str, tool_name: Optional[str] = None) -> str:
        failure_type = classify_failure(error_msg, tool_name or "")
        
        count = self.retry_counts.get(task.task_id, 0)
        policy = get_recovery_policy(failure_type, count)
        
        self.retry_counts[task.task_id] = count + 1
        
        logger.warning(f"Task {task.task_id} failed. Type: {failure_type}. Policy: {policy}. Retry count: {count}")
        return policy
