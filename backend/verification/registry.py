import logging
from typing import Callable, List, Optional


from backend.models.task import Task
from backend.verification.verifier import BaseVerifier

logger = logging.getLogger(__name__)


class VerifierRegistry:
    """Registry managing domain verifiers for autonomous task verification.

    Maintains an ordered collection of BaseVerifier instances and selects
    the first matching verifier for a given Task in deterministic order.
    """

    def __init__(self, verifiers: Optional[List[BaseVerifier]] = None) -> None:
        self._verifiers: List[BaseVerifier] = list(verifiers) if verifiers else []

    def __len__(self) -> int:
        return len(self._verifiers)

    @property
    def verifiers(self) -> List[BaseVerifier]:
        """Returns a copy of the registered verifiers in registration order."""
        return list(self._verifiers)

    def register(self, verifier: BaseVerifier) -> None:
        """Registers a verifier instance. Verifiers are evaluated in order of registration."""
        if verifier not in self._verifiers:
            self._verifiers.append(verifier)
            logger.debug(f"Registered verifier: {verifier.__class__.__name__}")

    def replace_verifier(
        self,
        replacement: BaseVerifier,
        matcher: Callable[[BaseVerifier], bool],
    ) -> bool:
        """Replaces the first verifier matching matcher with replacement.

        Returns True if a verifier was replaced, False otherwise. Preserves the
        exact relative order of all other registered verifiers.
        """
        for idx, v in enumerate(self._verifiers):
            if matcher(v):
                self._verifiers[idx] = replacement
                logger.debug(f"Replaced verifier at index {idx} with {replacement.__class__.__name__}")
                return True
        return False


    def get_verifier(self, task: Task) -> Optional[BaseVerifier]:
        """Returns the first registered verifier whose can_verify(task) returns True,
        or None if no verifier matches.
        """
        for verifier in self._verifiers:
            try:
                if verifier.can_verify(task):
                    return verifier
            except Exception as e:
                logger.warning(f"Error checking can_verify on {verifier.__class__.__name__}: {e}")
                continue
        return None


def get_default_verifier_registry() -> VerifierRegistry:
    """Creates a VerifierRegistry pre-configured with the default FinanceInvoiceVerifier."""
    from backend.verification.finance_verifier import FinanceInvoiceVerifier

    registry = VerifierRegistry()
    registry.register(FinanceInvoiceVerifier())
    return registry
