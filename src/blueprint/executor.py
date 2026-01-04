"""Blueprint executor - orchestrates task execution with real parallel support.

v1.0.0: Implements real asyncio.gather() parallel execution.
v1.1.0: Adds structured logging with correlation IDs.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable, Any
from blueprint.models import Blueprint, Task, TaskStatus
from blueprint.scheduler import ExecutionPlan, create_execution_plan, get_next_tasks
from blueprint.logging import (
    get_logger,
    CorrelationContext,
    set_blueprint_id,
    generate_correlation_id,
)


class ExecutionMode(Enum):
    DRY_RUN = "dry_run"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class TaskResult:
    """Result of executing a single task."""
    task_id: str
    success: bool
    start_time: datetime
    end_time: Optional[datetime] = None
    output: Optional[str] = None
    error: Optional[str] = None
    test_passed: Optional[bool] = None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


@dataclass
class ExecutionState:
    """Current state of Blueprint execution."""
    blueprint_title: str
    mode: ExecutionMode
    started_at: datetime
    correlation_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    current_group: Optional[str] = None
    results: dict[str, TaskResult] = field(default_factory=dict)
    pending_human: list[str] = field(default_factory=list)
    parallel_stats: dict[str, Any] = field(default_factory=dict)
    
    @property
    def completed_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results.values() if not r.success)
    
    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None
    
    def summary(self) -> str:
        status = "COMPLETE" if self.is_complete else "IN PROGRESS"
        lines = [
            "Execution: " + self.blueprint_title,
            "Status: " + status,
            "Mode: " + self.mode.value,
            "Correlation ID: " + (self.correlation_id or "N/A"),
            "Completed: " + str(self.completed_count),
            "Failed: " + str(self.failed_count),
        ]
        if self.pending_human:
            lines.append("Awaiting human: " + str(len(self.pending_human)))
        if self.parallel_stats:
            lines.append(f"Parallel groups: {self.parallel_stats.get('groups_executed', 0)}")
            lines.append(f"Max concurrency: {self.parallel_stats.get('max_concurrency', 0)}")
        return chr(10).join(lines)


class BlueprintExecutor:
    """Executes Blueprint tasks with dependency tracking and real parallel execution.
    
    v1.1.0: All execution is wrapped in a CorrelationContext for observability.
    """
    
    def __init__(self, blueprint: Blueprint):
        self.blueprint = blueprint
        self._state: Optional[ExecutionState] = None
        self._plan: Optional[ExecutionPlan] = None
        self._task_handler: Optional[Callable[[Task], TaskResult]] = None
        self._async_task_handler: Optional[Callable[[Task], Any]] = None
        self._logger = get_logger("blueprint.executor")
    
    def plan(self) -> ExecutionPlan:
        if self._plan is None:
            self._plan = create_execution_plan(self.blueprint)
        return self._plan
    
    def set_task_handler(self, handler: Callable[[Task], TaskResult]) -> None:
        """Set synchronous task handler."""
        self._task_handler = handler
    
    def set_async_task_handler(self, handler: Callable[[Task], Any]) -> None:
        """Set async task handler for parallel execution.
        
        The handler should be an async function that accepts a Task and returns TaskResult.
        If not set, the sync handler will be wrapped for async execution.
        """
        self._async_task_handler = handler
    
    def execute(
        self,
        mode: ExecutionMode = ExecutionMode.DRY_RUN,
        correlation_id: Optional[str] = None,
    ) -> ExecutionState:
        """Execute the Blueprint with structured logging.
        
        Args:
            mode: Execution mode (DRY_RUN, SEQUENTIAL, or PARALLEL).
            correlation_id: Optional correlation ID for tracing. Auto-generated if not provided.
        
        Returns:
            ExecutionState with results and statistics.
        """
        # Generate correlation ID for this execution run
        cid = correlation_id or generate_correlation_id()
        
        with CorrelationContext(correlation_id=cid, blueprint_id=self.blueprint.metadata.title):
            self._state = ExecutionState(
                blueprint_title=self.blueprint.metadata.title,
                mode=mode,
                started_at=datetime.now(timezone.utc),
                correlation_id=cid,
            )
            
            plan = self.plan()
            
            self._logger.info(
                f"Execution started: {self.blueprint.metadata.title}",
                component="executor",
                extra={
                    "mode": mode.value,
                    "total_tasks": len(self.blueprint.tasks),
                    "total_groups": len(plan.groups),
                },
            )
            
            if mode == ExecutionMode.DRY_RUN:
                self._logger.info("Dry run mode - skipping actual execution", component="executor")
                self._state.completed_at = datetime.now(timezone.utc)
                return self._state
            
            groups_executed = 0
            max_concurrency = 0
            
            for group in plan.groups:
                self._state.current_group = group.group_id
                group_size = len(group.tasks)
                
                self._logger.info(
                    f"Starting group: {group.group_id}",
                    group_id=group.group_id,
                    component="executor",
                    extra={"task_count": group_size},
                )
                
                if mode == ExecutionMode.SEQUENTIAL:
                    self._execute_sequential(group.tasks)
                else:
                    # Real parallel execution
                    self._execute_parallel(group.tasks)
                    groups_executed += 1
                    max_concurrency = max(max_concurrency, group_size)
                
                self._logger.info(
                    f"Completed group: {group.group_id}",
                    group_id=group.group_id,
                    component="executor",
                    extra={
                        "completed": self._state.completed_count,
                        "failed": self._state.failed_count,
                    },
                )
                
                if self._should_stop():
                    self._logger.warning(
                        "Execution halted due to failures",
                        component="executor",
                        extra={"failed_count": self._state.failed_count},
                    )
                    break
            
            # Record parallel execution stats
            if mode == ExecutionMode.PARALLEL:
                self._state.parallel_stats = {
                    "groups_executed": groups_executed,
                    "max_concurrency": max_concurrency,
                    "total_tasks": len(self._state.results),
                }
            
            self._state.completed_at = datetime.now(timezone.utc)
            self._state.current_group = None
            
            duration_ms = (self._state.completed_at - self._state.started_at).total_seconds() * 1000
            self._logger.info(
                f"Execution complete: {self.blueprint.metadata.title}",
                component="executor",
                duration_ms=duration_ms,
                extra={
                    "completed": self._state.completed_count,
                    "failed": self._state.failed_count,
                    "parallel_stats": self._state.parallel_stats,
                },
            )
            
            return self._state
    
    def _execute_sequential(self, task_ids: list[str]) -> None:
        """Execute tasks one at a time, stopping on first failure."""
        for task_id in task_ids:
            task = self.blueprint.get_task(task_id)
            if task:
                result = self._execute_task(task)
                self._state.results[task_id] = result
                if not result.success:
                    break
    
    def _execute_parallel(self, task_ids: list[str]) -> None:
        """Execute tasks concurrently using asyncio.gather().
        
        All tasks in the group run simultaneously. Results are collected
        after all complete (or fail). Unlike sequential execution, we don't
        stop on first failure - we let all tasks complete for maximum throughput.
        """
        if not task_ids:
            return
        
        # Get all tasks
        tasks = []
        for task_id in task_ids:
            task = self.blueprint.get_task(task_id)
            if task:
                tasks.append(task)
        
        if not tasks:
            return
        
        # Run all tasks concurrently
        try:
            # Check if we're already in an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context - can't use asyncio.run()
                # Create tasks and gather them
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
                    futures = [executor.submit(self._execute_task, task) for task in tasks]
                    for task, future in zip(tasks, futures):
                        result = future.result()
                        self._state.results[task.task_id] = result
            except RuntimeError:
                # No running loop - safe to use asyncio.run()
                results = asyncio.run(self._execute_tasks_async(tasks))
                for task, result in zip(tasks, results):
                    self._state.results[task.task_id] = result
        except Exception as e:
            # Fallback to sequential on async errors
            self._logger.error(
                f"Parallel execution error, falling back to sequential: {e}",
                component="executor",
            )
            for task in tasks:
                if task.task_id not in self._state.results:
                    result = self._execute_task(task)
                    self._state.results[task.task_id] = result
    
    async def _execute_tasks_async(self, tasks: list[Task]) -> list[TaskResult]:
        """Execute multiple tasks concurrently and return all results."""
        coroutines = [self._execute_task_async(task) for task in tasks]
        # return_exceptions=True ensures we get results even if some fail
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        
        # Convert exceptions to TaskResults
        final_results = []
        for task, result in zip(tasks, results):
            if isinstance(result, Exception):
                self._logger.error(
                    f"Task failed with exception: {result}",
                    task_id=task.task_id,
                    component="executor",
                )
                final_results.append(TaskResult(
                    task_id=task.task_id,
                    success=False,
                    start_time=datetime.now(timezone.utc),
                    end_time=datetime.now(timezone.utc),
                    error=str(result),
                ))
            else:
                final_results.append(result)
        
        return final_results
    
    async def _execute_task_async(self, task: Task) -> TaskResult:
        """Async wrapper for task execution."""
        if self._async_task_handler:
            # Use provided async handler
            return await self._async_task_handler(task)
        
        # Wrap sync handler in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._execute_task, task)
    
    def _execute_task(self, task: Task) -> TaskResult:
        """Execute a single task synchronously with logging."""
        start_time = datetime.now(timezone.utc)
        
        self._logger.debug(
            f"Task starting: {task.task_id}",
            task_id=task.task_id,
            component="executor",
        )
        
        if task.requires_human():
            self._state.pending_human.append(task.task_id)
            self._logger.warning(
                f"Task requires human action: {task.human_required.action}",
                task_id=task.task_id,
                component="executor",
            )
            return TaskResult(
                task_id=task.task_id,
                success=False,
                start_time=start_time,
                end_time=datetime.now(timezone.utc),
                error="HUMAN_REQUIRED: " + task.human_required.action,
            )
        
        if self._task_handler:
            result = self._task_handler(task)
        else:
            result = TaskResult(
                task_id=task.task_id,
                success=True,
                start_time=start_time,
                end_time=datetime.now(timezone.utc),
                output="Simulated execution of " + task.name,
                test_passed=True,
            )
        
        duration_ms = None
        if result.duration_seconds:
            duration_ms = result.duration_seconds * 1000
        
        if result.success:
            self._logger.info(
                f"Task completed: {task.task_id}",
                task_id=task.task_id,
                component="executor",
                duration_ms=duration_ms,
            )
        else:
            self._logger.error(
                f"Task failed: {task.task_id}",
                task_id=task.task_id,
                component="executor",
                duration_ms=duration_ms,
                extra={"error": result.error},
            )
        
        return result
    
    def _should_stop(self) -> bool:
        """Check if execution should halt (any task failed)."""
        return self._state.failed_count > 0
    
    def get_ready_tasks(self) -> list[Task]:
        """Get tasks ready for execution (dependencies satisfied)."""
        return get_next_tasks(self.blueprint)
    
    @property
    def state(self) -> Optional[ExecutionState]:
        return self._state


def execute_blueprint(
    blueprint: Blueprint,
    mode: ExecutionMode = ExecutionMode.DRY_RUN,
    task_handler: Optional[Callable[[Task], TaskResult]] = None,
    correlation_id: Optional[str] = None,
) -> ExecutionState:
    """Convenience function to execute a Blueprint.
    
    Args:
        blueprint: The Blueprint to execute.
        mode: Execution mode (DRY_RUN, SEQUENTIAL, or PARALLEL).
        task_handler: Optional callback for task execution.
        correlation_id: Optional correlation ID for tracing.
    
    Returns:
        ExecutionState with results and statistics.
    
    Example:
        >>> state = execute_blueprint(bp, mode=ExecutionMode.PARALLEL)
        >>> print(state.correlation_id)
        'corr_a1b2c3d4e5f6'
        >>> print(state.parallel_stats)
        {'groups_executed': 3, 'max_concurrency': 4, 'total_tasks': 10}
    """
    executor = BlueprintExecutor(blueprint)
    if task_handler:
        executor.set_task_handler(task_handler)
    return executor.execute(mode, correlation_id=correlation_id)
