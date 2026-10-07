from enum import Enum


class ActionRisk(str, Enum):
    """Risk classifications for actions in the AURA system.

    Determines the safety evaluation policy applied prior to action execution.
    """

    READ = "READ"
    WRITE = "WRITE"
    SENSITIVE = "SENSITIVE"
    DESTRUCTIVE = "DESTRUCTIVE"
