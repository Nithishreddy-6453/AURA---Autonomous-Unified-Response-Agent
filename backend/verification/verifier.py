from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class VerificationResult:
    def __init__(self, is_verified: bool, details: str = "", expected: Optional[Dict[str, Any]] = None, actual: Optional[Dict[str, Any]] = None):
        self.is_verified = is_verified
        self.details = details
        self.expected = expected
        self.actual = actual

class BaseVerifier(ABC):
    @abstractmethod
    async def verify(self, task_metadata: Dict[str, Any], extracted_data: Dict[str, Any]) -> VerificationResult:
        pass
