"""Blueprint - Specification compiler for AI agent orchestration.

Blueprint transforms goals into structured, compilable, interface-first
contracts that enable parallel AI agent execution with coordination guarantees.

Example:
    >>> from blueprint import parse_file, validate, create_execution_plan
    >>> bp = parse_file("docs/MASTER_ROADMAP.md")
    >>> result = validate(bp)
    >>> if result.passed:
    ...     plan = create_execution_plan(bp)
    ...     print(f"Ready to execute {plan.total_tasks} tasks in {plan.group_count} groups")
"""
from blueprint.models import (
    Blueprint,
    Task,
    Tier,
    TaskStatus,
    TierStatus,
    Interface,
    HumanRequired,
    Notification,
    NotificationChannel,
    TimeoutAction,
    SuccessMetric,
    Metadata,
    DependencyGraph,
    DependencyEdge,
    ParallelGroup,
    DocumentControl,
    VersionHistoryEntry,
)
from blueprint.parser import parse_file, parse_json, parse_markdown, ParseError
from blueprint.validator import validate, validate_file, ValidationResult, ValidationError
from blueprint.scheduler import create_execution_plan, get_next_tasks, ExecutionPlan, ExecutionGroup
from blueprint.executor import (
    BlueprintExecutor,
    execute_blueprint,
    ExecutionMode,
    ExecutionState,
    TaskResult,
)

__version__ = "0.1.0"
__all__ = [
    # Models
    "Blueprint",
    "Task",
    "Tier",
    "TaskStatus",
    "TierStatus",
    "Interface",
    "HumanRequired",
    "Notification",
    "NotificationChannel",
    "TimeoutAction",
    "SuccessMetric",
    "Metadata",
    "DependencyGraph",
    "DependencyEdge",
    "ParallelGroup",
    "DocumentControl",
    "VersionHistoryEntry",
    # Parser
    "parse_file",
    "parse_json",
    "parse_markdown",
    "ParseError",
    # Validator
    "validate",
    "validate_file",
    "ValidationResult",
    "ValidationError",
    # Scheduler
    "create_execution_plan",
    "get_next_tasks",
    "ExecutionPlan",
    "ExecutionGroup",
    # Executor
    "BlueprintExecutor",
    "execute_blueprint",
    "ExecutionMode",
    "ExecutionState",
    "TaskResult",
]
