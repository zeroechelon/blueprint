"""Blueprint data models (Pydantic V2).

Defines the core data structures for Blueprint Standard Format v0.1.0.
Uses Pydantic for robust validation of LLM-generated outputs.

Migration from dataclasses to Pydantic V2 provides:
- Automatic type coercion (string "2" → int 2)
- Graceful handling of missing optional fields
- Better error messages for invalid inputs
- Serialization/deserialization built-in
"""
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskStatus(str, Enum):
    """Task execution status."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class TierStatus(str, Enum):
    """Tier execution status."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class NotificationChannel(str, Enum):
    """Notification delivery channel."""
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    ENV = "env"
    CONSOLE = "console"


class TimeoutAction(str, Enum):
    """Action to take on timeout or missing value."""
    ABORT = "abort"
    SKIP = "skip"
    CONTINUE = "continue"


class Notification(BaseModel):
    """Notification configuration for HUMAN_REQUIRED blocks."""
    channel: NotificationChannel
    recipient: Optional[str] = None
    variable: Optional[str] = None
    variables: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    webhook: Optional[str] = None
    
    model_config = {"extra": "ignore"}  # Tolerate unexpected fields from LLM


class HumanRequired(BaseModel):
    """Human-in-the-loop signal block."""
    action: str
    reason: str
    notify: Notification
    timeout: Optional[str] = None
    on_timeout: TimeoutAction = TimeoutAction.ABORT
    on_missing: TimeoutAction = TimeoutAction.ABORT
    
    model_config = {"extra": "ignore"}
    
    @field_validator("on_timeout", "on_missing", mode="before")
    @classmethod
    def parse_timeout_action(cls, v):
        """Handle 'ABORT with instructions' style strings from LLM."""
        if isinstance(v, str):
            v_lower = v.lower().split()[0]  # Take first word
            if v_lower in ("abort", "skip", "continue"):
                return v_lower
        return v


class Interface(BaseModel):
    """Task input/output contract."""
    input: str
    output: str
    
    model_config = {"extra": "ignore"}


class Task(BaseModel):
    """A single task in a Blueprint."""
    task_id: str
    name: str
    status: TaskStatus = TaskStatus.NOT_STARTED
    dependencies: list[str] = Field(default_factory=list)
    interface: Optional[Interface] = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    test_command: str = ""
    rollback: str = ""
    assignee: Optional[str] = None
    estimated_sessions: Optional[int] = None
    files_to_create: list[str] = Field(default_factory=list)
    files_to_modify: list[str] = Field(default_factory=list)
    human_required: Optional[HumanRequired] = None
    notes: Optional[str] = None
    example: Optional[dict] = None  # For example input/output
    
    model_config = {"extra": "ignore"}
    
    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, v):
        """Handle emoji status markers from markdown."""
        if isinstance(v, str):
            emoji_map = {
                "🔲": "not_started",
                "🔄": "in_progress", 
                "✅": "complete",
                "⛔": "blocked",
                "⏭️": "skipped",
            }
            # Check if starts with emoji
            for emoji, status in emoji_map.items():
                if v.startswith(emoji):
                    return status
            # Already lowercase status
            return v.lower().replace(" ", "_")
        return v
    
    @field_validator("estimated_sessions", mode="before")
    @classmethod
    def coerce_sessions(cls, v):
        """Coerce string to int for estimated_sessions."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return None
        return v
    
    def is_blocked(self) -> bool:
        """Check if task is blocked by dependencies or human requirement."""
        return self.status == TaskStatus.BLOCKED
    
    def requires_human(self) -> bool:
        """Check if task requires human intervention."""
        return self.human_required is not None


class Tier(BaseModel):
    """A tier (phase) in a Blueprint."""
    tier_id: str
    name: str
    tasks: list[Task] = Field(default_factory=list)
    goal: Optional[str] = None
    status: TierStatus = TierStatus.NOT_STARTED
    
    model_config = {"extra": "ignore"}
    
    def task_count(self) -> int:
        """Get total number of tasks in tier."""
        return len(self.tasks)
    
    def completed_count(self) -> int:
        """Get number of completed tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETE)
    
    @model_validator(mode="after")
    def compute_status(self):
        """Auto-compute tier status from tasks."""
        if not self.tasks:
            return self
        completed = self.completed_count()
        total = self.task_count()
        if completed == total:
            self.status = TierStatus.COMPLETE
        elif completed > 0:
            self.status = TierStatus.IN_PROGRESS
        elif any(t.status == TaskStatus.BLOCKED for t in self.tasks):
            self.status = TierStatus.BLOCKED
        return self


class SuccessMetric(BaseModel):
    """A success metric for the Blueprint."""
    metric: str
    target: str
    validation: Optional[str] = None
    
    model_config = {"extra": "ignore"}


class Metadata(BaseModel):
    """Blueprint document metadata."""
    title: str
    status: str = "draft"
    owner: str = "Unknown"
    description: Optional[str] = None
    created: Optional[date] = None
    updated: Optional[date] = None
    repository: Optional[str] = None
    
    model_config = {"extra": "ignore"}
    
    @field_validator("created", "updated", mode="before")
    @classmethod
    def parse_date(cls, v):
        """Parse date from string."""
        if isinstance(v, str):
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
        return v


class DependencyEdge(BaseModel):
    """An edge in the dependency graph."""
    from_task: str
    to_task: str


class ParallelGroup(BaseModel):
    """A group of tasks that can run in parallel."""
    group_id: str
    tasks: list[str]
    description: Optional[str] = None


class DependencyGraph(BaseModel):
    """Dependency graph structure."""
    nodes: list[str] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    parallelizable_groups: list[ParallelGroup] = Field(default_factory=list)


class VersionHistoryEntry(BaseModel):
    """A single entry in document version history."""
    version: str
    date: date
    author: str
    changes: str
    
    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        """Parse date from string."""
        if isinstance(v, str):
            try:
                return date.fromisoformat(v)
            except ValueError:
                return date.today()
        return v


class DocumentControl(BaseModel):
    """Document version control information."""
    version: str = "0.1.0"
    history: list[VersionHistoryEntry] = Field(default_factory=list)


class BlueprintRef(BaseModel):
    """Reference to another Blueprint (Linker support).
    
    Enables hierarchical compilation by allowing Blueprints to reference
    sub-modules. This prevents context window overflow for large projects.
    """
    ref: str  # Path to referenced Blueprint (e.g., "./auth-module.bp.md")
    required: bool = True  # If false, missing ref is warning not error
    inline: bool = False  # If true, inline tasks; if false, treat as dependency


class Blueprint(BaseModel):
    """A complete Blueprint specification.
    
    This is the top-level container that holds all components of a Blueprint
    document. It can be serialized to/from JSON and Markdown formats.
    
    Supports hierarchical compilation via `refs` field for large projects.
    """
    blueprint_version: str = "0.1.0"
    metadata: Metadata
    tiers: list[Tier] = Field(default_factory=list)
    strategic_vision: Optional[str] = None
    success_metrics: list[SuccessMetric] = Field(default_factory=list)
    dependency_graph: Optional[DependencyGraph] = None
    document_control: Optional[DocumentControl] = None
    refs: list[BlueprintRef] = Field(default_factory=list)  # Linker support
    
    model_config = {"extra": "ignore"}
    
    def all_tasks(self) -> list[Task]:
        """Get all tasks across all tiers."""
        return [task for tier in self.tiers for task in tier.tasks]
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        for task in self.all_tasks():
            if task.task_id == task_id:
                return task
        return None
    
    def total_tasks(self) -> int:
        """Get total number of tasks."""
        return len(self.all_tasks())
    
    def completed_tasks(self) -> int:
        """Get number of completed tasks."""
        return sum(1 for t in self.all_tasks() if t.status == TaskStatus.COMPLETE)
    
    def progress_percent(self) -> float:
        """Get completion percentage."""
        total = self.total_tasks()
        if total == 0:
            return 0.0
        return (self.completed_tasks() / total) * 100
    
    def has_refs(self) -> bool:
        """Check if Blueprint references other modules."""
        return len(self.refs) > 0
    
    def human_required_tasks(self) -> list[Task]:
        """Get all tasks requiring human intervention."""
        return [t for t in self.all_tasks() if t.requires_human()]
