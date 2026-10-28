"""StarHelp Windows desktop and local account component."""

from .analysis import ProducerAnalysisExecution, ProducerAnalysisRunner
from .equipment import (
    EquipmentIdentityService,
    EquipmentMergeConflict,
    EquipmentMergeConflictError,
)
from .models import (
    AccountSnapshot,
    EquipmentInstance,
    FieldFact,
    FieldStatus,
    Ownership,
    ProfileAuthorization,
    SourceKind,
)
from .planner import LocalPlannerProcess, PlannerCancelled, PlannerResult, PlannerUnavailable
from .producer_request import build_producer_analysis_request, select_public_task
from .progress import PlayerProgressEntry, ProgressRepository
from .tasks import AnalysisTaskDraft, TaskRepository, TaskState

__all__ = [
    "AccountSnapshot",
    "EquipmentInstance",
    "FieldFact",
    "FieldStatus",
    "Ownership",
    "ProfileAuthorization",
    "SourceKind",
    "AnalysisTaskDraft",
    "TaskRepository",
    "TaskState",
    "EquipmentIdentityService",
    "EquipmentMergeConflict",
    "EquipmentMergeConflictError",
    "LocalPlannerProcess",
    "PlannerCancelled",
    "PlannerResult",
    "PlannerUnavailable",
    "ProducerAnalysisExecution",
    "ProducerAnalysisRunner",
    "PlayerProgressEntry",
    "ProgressRepository",
    "build_producer_analysis_request",
    "select_public_task",
]
