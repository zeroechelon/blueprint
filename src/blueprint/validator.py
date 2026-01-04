"""Blueprint validator - pre-flight checks before execution.

Validates Blueprint structure, dependencies, and interfaces to catch
errors before dispatching to agents.
"""
from dataclasses import dataclass, field
from typing import Optional
from blueprint.models import Blueprint, Task, TaskStatus


@dataclass
class ValidationError:
    """A single validation error."""
    code: str
    message: str
    task_id: Optional[str] = None
    severity: str = "error"  # error, warning
    
    def __str__(self) -> str:
        if self.task_id:
            return f"[{self.code}] {self.task_id}: {self.message}"
        return f"[{self.code}] {self.message}"


@dataclass
class ValidationResult:
    """Result of Blueprint validation."""
    passed: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    
    @property
    def error_count(self) -> int:
        return len(self.errors)
    
    @property
    def warning_count(self) -> int:
        return len(self.warnings)
    
    def summary(self) -> str:
        if self.passed:
            if self.warnings:
                return f"✅ Valid with {self.warning_count} warning(s)"
            return "✅ Valid"
        return f"❌ Invalid: {self.error_count} error(s), {self.warning_count} warning(s)"


def validate(blueprint: Blueprint) -> ValidationResult:
    """Validate a Blueprint for correctness.
    
    Checks:
    - Unique task IDs
    - Valid dependency references
    - No circular dependencies
    - Interface compatibility (warnings)
    - Required fields present
    - Test commands non-empty
    
    Args:
        blueprint: Blueprint to validate
        
    Returns:
        ValidationResult with pass/fail and error details
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationError] = []
    
    all_tasks = blueprint.all_tasks()
    task_ids = {t.task_id for t in all_tasks}
    
    # Check 1: Unique task IDs
    seen_ids: set[str] = set()
    for task in all_tasks:
        if task.task_id in seen_ids:
            errors.append(ValidationError(
                code="DUPLICATE_ID",
                message=f"Duplicate task ID: {task.task_id}",
                task_id=task.task_id,
            ))
        seen_ids.add(task.task_id)
    
    # Check 2: Valid dependency references
    for task in all_tasks:
        for dep in task.dependencies:
            if dep not in task_ids:
                errors.append(ValidationError(
                    code="MISSING_DEP",
                    message=f"Dependency '{dep}' does not exist",
                    task_id=task.task_id,
                ))
    
    # Check 3: Circular dependencies
    circular = _detect_circular_dependencies(all_tasks)
    for cycle in circular:
        errors.append(ValidationError(
            code="CIRCULAR_DEP",
            message=f"Circular dependency detected: {' -> '.join(cycle)}",
        ))
    
    # Check 4: Required fields
    for task in all_tasks:
        if not task.task_id:
            errors.append(ValidationError(
                code="MISSING_FIELD",
                message="task_id is required",
                task_id="unknown",
            ))
        if not task.name:
            errors.append(ValidationError(
                code="MISSING_FIELD",
                message="name is required",
                task_id=task.task_id,
            ))
        if not task.test_command or not task.test_command.strip():
            errors.append(ValidationError(
                code="MISSING_TEST",
                message="test_command is required and cannot be empty",
                task_id=task.task_id,
            ))
        if not task.rollback or not task.rollback.strip():
            warnings.append(ValidationError(
                code="MISSING_ROLLBACK",
                message="rollback command is empty (recommended)",
                task_id=task.task_id,
                severity="warning",
            ))
        if not task.acceptance_criteria:
            warnings.append(ValidationError(
                code="NO_CRITERIA",
                message="No acceptance criteria defined",
                task_id=task.task_id,
                severity="warning",
            ))
    
    # Check 5: Interface compatibility (warning only)
    interface_issues = _check_interface_compatibility(all_tasks)
    for issue in interface_issues:
        warnings.append(issue)
    
    # Check 6: Metadata
    if not blueprint.metadata.title:
        warnings.append(ValidationError(
            code="NO_TITLE",
            message="Blueprint has no title",
            severity="warning",
        ))
    if not blueprint.metadata.owner:
        warnings.append(ValidationError(
            code="NO_OWNER",
            message="Blueprint has no owner",
            severity="warning",
        ))
    
    passed = len(errors) == 0
    return ValidationResult(passed=passed, errors=errors, warnings=warnings)


def _detect_circular_dependencies(tasks: list[Task]) -> list[list[str]]:
    """Detect circular dependencies using DFS.
    
    Returns list of cycles found (each cycle is a list of task IDs).
    """
    # Build adjacency list
    graph: dict[str, list[str]] = {}
    for task in tasks:
        graph[task.task_id] = task.dependencies.copy()
    
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    
    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
        
        path.pop()
        rec_stack.remove(node)
    
    for task_id in graph:
        if task_id not in visited:
            dfs(task_id, [])
    
    return cycles


def _check_interface_compatibility(tasks: list[Task]) -> list[ValidationError]:
    """Check interface compatibility between dependent tasks.
    
    This is a heuristic check - we look for obvious mismatches.
    Returns warnings, not errors, since interfaces are loosely typed.
    """
    warnings: list[ValidationError] = []
    task_map = {t.task_id: t for t in tasks}
    
    for task in tasks:
        for dep_id in task.dependencies:
            dep_task = task_map.get(dep_id)
            if not dep_task:
                continue
            
            # Check if output of dependency could satisfy input of this task
            dep_output = dep_task.interface.output.lower()
            task_input = task.interface.input.lower()
            
            # Very basic heuristic: warn if they seem unrelated
            # This is intentionally loose - interfaces are documentation
            if dep_output and task_input:
                # Check for some common terms
                dep_terms = set(dep_output.split())
                input_terms = set(task_input.split())
                
                # If no overlap at all, might be a mismatch
                common = dep_terms & input_terms
                if not common and len(dep_terms) > 2 and len(input_terms) > 2:
                    warnings.append(ValidationError(
                        code="INTERFACE_MISMATCH",
                        message=f"Interface may not match: {dep_id} outputs '{dep_task.interface.output[:50]}...' but {task.task_id} expects '{task.interface.input[:50]}...'",
                        task_id=task.task_id,
                        severity="warning",
                    ))
    
    return warnings


def validate_file(filepath: str) -> ValidationResult:
    """Convenience function to validate a Blueprint file.
    
    Args:
        filepath: Path to Blueprint file (.md or .json)
        
    Returns:
        ValidationResult
    """
    from blueprint.parser import parse_file
    blueprint = parse_file(filepath)
    return validate(blueprint)
