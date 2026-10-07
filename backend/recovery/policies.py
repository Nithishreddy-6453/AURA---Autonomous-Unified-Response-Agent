from backend.recovery.classifier import FailureType

def get_recovery_policy(failure_type: FailureType, retry_count: int, max_retries: int = 3) -> str:
    if retry_count >= max_retries:
        return "ESCALATE"
    
    if failure_type == FailureType.TRANSIENT:
        return "RETRY"
    elif failure_type == FailureType.NAVIGATION_STATE:
        return "RESET_AND_RETRY"
    elif failure_type == FailureType.VALIDATION:
        return "CORRECT_DATA"
    elif failure_type == FailureType.DUPLICATE:
        return "ESCALATE"
    else:
        return "ESCALATE"
