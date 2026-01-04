"""Blueprint scheduler - determines execution order and parallelization.

Analyzes the dependency graph to produce an optimal execution plan
that maximizes parallelization while respecting dependencies.
"""
from dataclasses import dataclass, field
from typing import Optional
from blueprint.models import Blueprint, Task, TaskStatus, DependencyGraph


@dataclass
class ExecutionGroup:
    """A group of tasks that can execute in parallel."""
    group_id: str
    tasks: list[str]
    description: Optional[str] = None
    
    def __len__(self) -> int:
        return len(self.tasks)


@dataclass
class ExecutionPlan:
    """A complete execution plan for a Blueprint."""
    blueprint_title: str
    total_tasks: int
    groups: list[ExecutionGroup] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)
    human_required_tasks: list[str] = field(default_factory=list)
    
    @property
    def group_count(self) -> int:
        return len(self.groups)
    
    @property 
    def max_parallelism(self) -> int:
        if not self.groups:
            return 0
        return max(len(g) for g in self.groups)
    
    def summary(self) -> str:
        lines = [
            "Execution Plan: " + self.blueprint_title,
            "Total tasks: " + str(self.total_tasks),
            "Execution groups: " + str(self.group_count),
            "Max parallelism: " + str(self.max_parallelism),
        ]
        if self.human_required_tasks:
            lines.append("Human required: " + str(len(self.human_required_tasks)) + " task(s)")
        if self.blocked_tasks:
            lines.append("Blocked: " + str(len(self.blocked_tasks)) + " task(s)")
        return chr(10).join(lines)
    
    def to_dict(self) -> dict:
        return {
            "blueprint_title": self.blueprint_title,
            "total_tasks": self.total_tasks,
            "group_count": self.group_count,
            "max_parallelism": self.max_parallelism,
            "groups": [
                {
                    "group_id": g.group_id,
                    "tasks": g.tasks,
                    "description": g.description,
                    "parallelism": len(g),
                }
                for g in self.groups
            ],
            "human_required_tasks": self.human_required_tasks,
            "blocked_tasks": self.blocked_tasks,
        }


def create_execution_plan(blueprint: Blueprint) -> ExecutionPlan:
    """Create an execution plan from a Blueprint."""
    all_tasks = blueprint.all_tasks()
    task_map = {t.task_id: t for t in all_tasks}
    
    in_degree: dict[str, int] = {}
    dependents: dict[str, list[str]] = {}
    
    for task in all_tasks:
        in_degree[task.task_id] = len(task.dependencies)
        dependents[task.task_id] = []
    
    for task in all_tasks:
        for dep in task.dependencies:
            if dep in dependents:
                dependents[dep].append(task.task_id)
    
    human_required = [t.task_id for t in all_tasks if t.requires_human()]
    completed = {t.task_id for t in all_tasks if t.status == TaskStatus.COMPLETE}
    blocked = [t.task_id for t in all_tasks if t.status == TaskStatus.BLOCKED]
    
    groups: list[ExecutionGroup] = []
    remaining = set(in_degree.keys()) - completed
    group_num = 0
    
    while remaining:
        ready = [
            task_id for task_id in remaining
            if in_degree[task_id] == 0 or all(
                dep in completed for dep in task_map[task_id].dependencies
            )
        ]
        
        if not ready:
            blocked.extend(remaining)
            break
        
        group_num += 1
        group = ExecutionGroup(
            group_id="G" + str(group_num),
            tasks=sorted(ready),
            description="Parallel group " + str(group_num) + " (" + str(len(ready)) + " tasks)",
        )
        groups.append(group)
        
        for task_id in ready:
            completed.add(task_id)
            remaining.remove(task_id)
            for dependent in dependents.get(task_id, []):
                if dependent in in_degree:
                    in_degree[dependent] -= 1
    
    return ExecutionPlan(
        blueprint_title=blueprint.metadata.title,
        total_tasks=len(all_tasks),
        groups=groups,
        blocked_tasks=blocked,
        human_required_tasks=human_required,
    )


def get_next_tasks(blueprint: Blueprint) -> list[Task]:
    """Get tasks that are ready to execute now."""
    all_tasks = blueprint.all_tasks()
    task_map = {t.task_id: t for t in all_tasks}
    completed = {t.task_id for t in all_tasks if t.status == TaskStatus.COMPLETE}
    
    ready = []
    for task in all_tasks:
        if task.status in (TaskStatus.COMPLETE, TaskStatus.BLOCKED, TaskStatus.SKIPPED):
            continue
        deps_satisfied = all(dep in completed for dep in task.dependencies)
        if deps_satisfied:
            ready.append(task)
    
    return ready


def estimate_execution_time(plan: ExecutionPlan, sessions_per_group: float = 2.0) -> float:
    """Estimate total execution time in sessions."""
    return len(plan.groups) * sessions_per_group
