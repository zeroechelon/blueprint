"""Tests for the Blueprint executor with parallel execution.

These tests verify the executor handles sequential and parallel modes correctly,
including edge cases like failures and human-required tasks.
"""
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import pytest

from blueprint.executor import (
    BlueprintExecutor,
    ExecutionMode,
    TaskResult,
    ExecutionState,
    execute_blueprint,
)
from blueprint.models import Blueprint, Task, Metadata, HumanRequired


class MockBlueprint:
    """Mock Blueprint for testing."""
    
    def __init__(self, tasks: list[Task]):
        self._tasks = {t.task_id: t for t in tasks}
        self.metadata = Metadata(title="Test Blueprint", version="1.0")
    
    def get_task(self, task_id: str) -> Task:
        return self._tasks.get(task_id)
    
    @property
    def tasks(self) -> list[Task]:
        return list(self._tasks.values())


class MockExecutionPlan:
    """Mock execution plan for testing."""
    
    def __init__(self, groups):
        self.groups = groups


class MockExecutionGroup:
    """Mock execution group for testing."""
    
    def __init__(self, group_id: str, tasks: list[str]):
        self.group_id = group_id
        self.tasks = tasks


def create_simple_task(task_id: str, name: str = None) -> Task:
    """Create a simple task for testing."""
    return Task(
        task_id=task_id,
        name=name or f"Task {task_id}",
        dependencies=[],
        acceptance_criteria=["Done"],
    )


def create_human_task(task_id: str, action: str = "Approve") -> Task:
    """Create a task requiring human intervention."""
    return Task(
        task_id=task_id,
        name=f"Human Task {task_id}",
        dependencies=[],
        acceptance_criteria=["Approved"],
        human_required=HumanRequired(
            action=action,
            reason="Testing",
            notify={"channel": "console"},
        ),
    )


class TestExecutionMode:
    """Test execution mode enumeration."""
    
    def test_modes_exist(self):
        assert ExecutionMode.DRY_RUN.value == "dry_run"
        assert ExecutionMode.SEQUENTIAL.value == "sequential"
        assert ExecutionMode.PARALLEL.value == "parallel"


class TestTaskResult:
    """Test TaskResult dataclass."""
    
    def test_duration_calculation(self):
        start = datetime.now(timezone.utc)
        time.sleep(0.01)  # 10ms
        end = datetime.now(timezone.utc)
        
        result = TaskResult(
            task_id="T1",
            success=True,
            start_time=start,
            end_time=end,
        )
        
        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0.01
    
    def test_duration_none_without_end(self):
        result = TaskResult(
            task_id="T1",
            success=True,
            start_time=datetime.now(timezone.utc),
        )
        
        assert result.duration_seconds is None


class TestExecutionState:
    """Test ExecutionState dataclass."""
    
    def test_completed_count(self):
        state = ExecutionState(
            blueprint_title="Test",
            mode=ExecutionMode.PARALLEL,
            started_at=datetime.now(timezone.utc),
        )
        
        state.results["T1"] = TaskResult("T1", True, datetime.now(timezone.utc))
        state.results["T2"] = TaskResult("T2", True, datetime.now(timezone.utc))
        state.results["T3"] = TaskResult("T3", False, datetime.now(timezone.utc))
        
        assert state.completed_count == 2
        assert state.failed_count == 1
    
    def test_summary_includes_parallel_stats(self):
        state = ExecutionState(
            blueprint_title="Test",
            mode=ExecutionMode.PARALLEL,
            started_at=datetime.now(timezone.utc),
            parallel_stats={"groups_executed": 3, "max_concurrency": 4},
        )
        
        summary = state.summary()
        assert "Parallel groups: 3" in summary
        assert "Max concurrency: 4" in summary


class TestBlueprintExecutor:
    """Test BlueprintExecutor class."""
    
    def test_dry_run_returns_immediately(self):
        tasks = [create_simple_task("T1")]
        blueprint = MockBlueprint(tasks)
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([])
            executor = BlueprintExecutor(blueprint)
            state = executor.execute(ExecutionMode.DRY_RUN)
        
        assert state.is_complete
        assert state.completed_count == 0  # No tasks executed
    
    def test_sequential_executes_in_order(self):
        tasks = [create_simple_task("T1"), create_simple_task("T2")]
        blueprint = MockBlueprint(tasks)
        
        execution_order = []
        def handler(task):
            execution_order.append(task.task_id)
            return TaskResult(task.task_id, True, datetime.now(timezone.utc))
        
        group = MockExecutionGroup("G1", ["T1", "T2"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            executor.set_task_handler(handler)
            state = executor.execute(ExecutionMode.SEQUENTIAL)
        
        assert execution_order == ["T1", "T2"]
        assert state.completed_count == 2
    
    def test_sequential_stops_on_failure(self):
        tasks = [create_simple_task("T1"), create_simple_task("T2")]
        blueprint = MockBlueprint(tasks)
        
        def handler(task):
            success = task.task_id != "T1"  # T1 fails
            return TaskResult(task.task_id, success, datetime.now(timezone.utc))
        
        group = MockExecutionGroup("G1", ["T1", "T2"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            executor.set_task_handler(handler)
            state = executor.execute(ExecutionMode.SEQUENTIAL)
        
        assert state.failed_count == 1
        assert "T2" not in state.results  # T2 never executed
    
    def test_parallel_executes_all_tasks(self):
        tasks = [create_simple_task(f"T{i}") for i in range(1, 5)]
        blueprint = MockBlueprint(tasks)
        
        executed = []
        def handler(task):
            executed.append(task.task_id)
            return TaskResult(task.task_id, True, datetime.now(timezone.utc))
        
        group = MockExecutionGroup("G1", ["T1", "T2", "T3", "T4"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            executor.set_task_handler(handler)
            state = executor.execute(ExecutionMode.PARALLEL)
        
        assert len(executed) == 4
        assert state.completed_count == 4
        assert state.parallel_stats["max_concurrency"] == 4
    
    def test_parallel_collects_failures(self):
        """Parallel execution should complete all tasks even with failures."""
        tasks = [create_simple_task(f"T{i}") for i in range(1, 4)]
        blueprint = MockBlueprint(tasks)
        
        def handler(task):
            success = task.task_id != "T2"  # T2 fails
            return TaskResult(task.task_id, success, datetime.now(timezone.utc))
        
        group = MockExecutionGroup("G1", ["T1", "T2", "T3"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            executor.set_task_handler(handler)
            state = executor.execute(ExecutionMode.PARALLEL)
        
        # All tasks should be in results, unlike sequential which stops
        assert len(state.results) == 3
        assert state.completed_count == 2
        assert state.failed_count == 1
    
    def test_human_required_task_recorded(self):
        tasks = [create_human_task("T1", "Click approve button")]
        blueprint = MockBlueprint(tasks)
        
        group = MockExecutionGroup("G1", ["T1"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            state = executor.execute(ExecutionMode.SEQUENTIAL)
        
        assert "T1" in state.pending_human
        assert state.results["T1"].success is False
        assert "HUMAN_REQUIRED" in state.results["T1"].error
    
    def test_parallel_stats_populated(self):
        tasks = [create_simple_task(f"T{i}") for i in range(1, 6)]
        blueprint = MockBlueprint(tasks)
        
        group1 = MockExecutionGroup("G1", ["T1", "T2"])
        group2 = MockExecutionGroup("G2", ["T3", "T4", "T5"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group1, group2])
            executor = BlueprintExecutor(blueprint)
            state = executor.execute(ExecutionMode.PARALLEL)
        
        assert state.parallel_stats["groups_executed"] == 2
        assert state.parallel_stats["max_concurrency"] == 3  # G2 has 3 tasks
        assert state.parallel_stats["total_tasks"] == 5


class TestExecuteBlueprintFunction:
    """Test convenience function."""
    
    def test_execute_blueprint_with_handler(self):
        tasks = [create_simple_task("T1")]
        blueprint = MockBlueprint(tasks)
        
        handler_called = []
        def handler(task):
            handler_called.append(task.task_id)
            return TaskResult(task.task_id, True, datetime.now(timezone.utc))
        
        group = MockExecutionGroup("G1", ["T1"])
        
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            state = execute_blueprint(
                blueprint,
                mode=ExecutionMode.PARALLEL,
                task_handler=handler,
            )
        
        assert handler_called == ["T1"]
        assert state.completed_count == 1


class TestParallelTiming:
    """Test that parallel execution actually runs concurrently."""
    
    def test_parallel_faster_than_sequential(self):
        """Parallel execution of slow tasks should be faster than sequential."""
        tasks = [create_simple_task(f"T{i}") for i in range(1, 4)]
        blueprint = MockBlueprint(tasks)
        
        def slow_handler(task):
            time.sleep(0.05)  # 50ms per task
            return TaskResult(task.task_id, True, datetime.now(timezone.utc))
        
        group = MockExecutionGroup("G1", ["T1", "T2", "T3"])
        
        # Time sequential
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            executor.set_task_handler(slow_handler)
            
            seq_start = time.time()
            executor.execute(ExecutionMode.SEQUENTIAL)
            seq_duration = time.time() - seq_start
        
        # Time parallel
        with patch("blueprint.executor.create_execution_plan") as mock_plan:
            mock_plan.return_value = MockExecutionPlan([group])
            executor = BlueprintExecutor(blueprint)
            executor.set_task_handler(slow_handler)
            
            par_start = time.time()
            executor.execute(ExecutionMode.PARALLEL)
            par_duration = time.time() - par_start
        
        # Parallel should be significantly faster
        # Sequential: ~150ms (3 * 50ms)
        # Parallel: ~50ms (all concurrent)
        assert par_duration < seq_duration * 0.7  # At least 30% faster

