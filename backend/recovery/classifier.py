from enum import Enum

class FailureType(Enum):
    VALIDATION = "validation"
    DUPLICATE = "duplicate"
    NOT_FOUND = "not_found"
    NAVIGATION_STATE = "navigation_state"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"

def classify_failure(error_msg: str, tool_name: str) -> FailureType:
    error_msg = error_msg.lower()
    if "validation" in error_msg or "data mismatch" in error_msg or "incorrect" in error_msg or "verification failed" in error_msg:
        return FailureType.VALIDATION
    if "duplicate" in error_msg or "already exists" in error_msg:
        return FailureType.DUPLICATE
    if "not found" in error_msg or "404" in error_msg:
        return FailureType.NOT_FOUND
    if "timeout" in error_msg or "connection" in error_msg:
        return FailureType.TRANSIENT
    if tool_name and tool_name.startswith("browser_") and ("element" in error_msg or "selector" in error_msg):
        return FailureType.NAVIGATION_STATE
    return FailureType.UNKNOWN
