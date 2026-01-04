"""Goal Decomposition Engine.

Transforms natural language goals into atomic tasks using Claude 4.5.
Part of Blueprint Tier 2: Generator Core.

Design Principles:
- Each task should fit within a single agent context window
- Tasks are atomic: one clear deliverable per task
- Dependencies are explicit (DAG structure)
- Session estimates are conservative

Environment:
    ANTHROPIC_API_KEY: Required for Claude API access

Changes (P0 Hardening):
- Added tenacity retry with exponential backoff for LLM calls
- Returns list[Task] models instead of list[dict] for type safety
"""
import json
import os
from typing import Optional

from anthropic import Anthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from blueprint.models import Task, TaskStatus, Interface

# Model hierarchy: prefer Opus, fallback to Sonnet
MODEL_OPUS = "claude-opus-4-5-20251101"
MODEL_SONNET = "claude-sonnet-4-5-20250929"

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 1  # seconds
RETRY_MAX_WAIT = 30  # seconds


class DecompositionError(Exception):
    """Raised when goal decomposition fails."""
    pass


class GoalDecomposer:
    """Decomposes natural language goals into atomic tasks.
    
    Uses Claude 4.5 to intelligently break down complex goals into
    manageable, atomic tasks with clear dependencies.
    
    Example:
        >>> decomposer = GoalDecomposer()
        >>> tasks = decomposer.decompose("Build a user authentication system with JWT")
        >>> print(len(tasks))
        5
        >>> print(tasks[0].name)
        "Set up project structure and dependencies"
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = MODEL_OPUS,
        max_tasks: int = 20,
    ):
        """Initialize the decomposer.
        
        Args:
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            model: Model to use. Defaults to Opus 4.5.
            max_tasks: Maximum tasks to generate per decomposition.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise DecompositionError(
                "ANTHROPIC_API_KEY not provided. Set environment variable or pass api_key parameter."
            )
        
        self.client = Anthropic(api_key=self.api_key)
        self.model = model
        self.max_tasks = max_tasks
    
    def decompose(
        self,
        goal: str,
        context: Optional[str] = None,
        existing_code: Optional[str] = None,
        return_dicts: bool = False,
    ) -> list[Task]:
        """Decompose a goal into atomic tasks.
        
        Args:
            goal: Natural language description of the goal.
            context: Optional additional context (tech stack, constraints).
            existing_code: Optional existing codebase context.
            return_dicts: If True, return list[dict] for backward compatibility.
        
        Returns:
            List of Task models (or dicts if return_dicts=True).
        
        Raises:
            DecompositionError: If decomposition fails after retries.
        """
        prompt = self._build_prompt(goal, context, existing_code)
        
        # Use retry-wrapped LLM call
        raw_tasks = self._call_llm_with_retry(prompt)
        
        # Validate task structure
        self._validate_tasks(raw_tasks)
        
        # Convert to Task models
        if return_dicts:
            return raw_tasks
        
        return self._convert_to_models(raw_tasks)
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def _call_llm_with_retry(self, prompt: str) -> list[dict]:
        """Call LLM with automatic retry on failure."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            
            content = response.content[0].text
            return self._parse_response(content)
            
        except Exception as e:
            # Log for debugging (will be caught by retry)
            raise DecompositionError(f"LLM call failed: {e}") from e
    
    def _convert_to_models(self, raw_tasks: list[dict]) -> list[Task]:
        """Convert raw task dicts to Task models."""
        tasks = []
        for raw in raw_tasks:
            # Build Interface if present
            interface = None
            if "interface" in raw:
                interface = Interface(
                    input=raw["interface"].get("input", ""),
                    output=raw["interface"].get("output", ""),
                )
            
            task = Task(
                task_id=raw["task_id"],
                name=raw["name"],
                status=TaskStatus.NOT_STARTED,
                dependencies=raw.get("dependencies", []),
                interface=interface,
                acceptance_criteria=raw.get("acceptance_criteria", []),
                test_command=raw.get("test_command", ""),
                rollback=raw.get("rollback", ""),
                estimated_sessions=raw.get("estimated_sessions"),
                files_to_create=raw.get("files_to_create", []),
                files_to_modify=raw.get("files_to_modify", []),
                notes=raw.get("description"),
            )
            tasks.append(task)
        
        return tasks
    
    def _build_prompt(
        self,
        goal: str,
        context: Optional[str],
        existing_code: Optional[str],
    ) -> str:
        """Build the decomposition prompt."""
        
        context_section = ""
        if context:
            context_section = f"""
## Additional Context
{context}
"""
        
        code_section = ""
        if existing_code:
            code_section = f"""
## Existing Codebase
```
{existing_code[:2000]}  # Truncate to avoid context overflow
```
"""
        
        return f"""You are a senior software architect decomposing a project goal into atomic tasks.

## Goal
{goal}
{context_section}{code_section}
## Requirements

Break this goal into **atomic tasks** following these rules:

1. **Atomicity**: Each task should be completable in 1-3 work sessions (2-6 hours total)
2. **Single Responsibility**: One clear deliverable per task
3. **Testable**: Each task must have verifiable acceptance criteria
4. **Dependencies**: Explicitly declare what each task depends on
5. **Files**: List specific files each task will create or modify
6. **No Overlap**: Tasks should not duplicate work

## Output Format

Return a JSON array of tasks. Each task must have:

```json
[
  {{
    "task_id": "T1",
    "name": "Short descriptive name",
    "description": "What this task accomplishes",
    "dependencies": [],
    "estimated_sessions": 1,
    "acceptance_criteria": [
      "Specific testable criterion 1",
      "Specific testable criterion 2"
    ],
    "files_to_create": ["src/module/file.py"],
    "files_to_modify": [],
    "requires_human": false,
    "human_action": null
  }}
]
```

**Task ID Convention**: Use T1, T2, T3... for sequential tasks. Group related tasks with decimal notation (T1.1, T1.2) if needed.

**Dependencies**: Reference task_ids of tasks that must complete first. Empty array for tasks with no dependencies.

**requires_human**: Set true if task needs human input (API keys, credentials, approvals).

## Constraints

- Maximum {self.max_tasks} tasks
- Each task should fit in a single agent context window
- Prefer more smaller tasks over fewer large tasks
- First task should always be project setup/scaffolding
- Last task should be integration/testing

Return ONLY the JSON array, no markdown fencing, no explanation."""

    def _parse_response(self, content: str) -> list[dict]:
        """Parse Claude's response into task list."""
        # Strip any markdown fencing if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        
        try:
            tasks = json.loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON array from response
            import re
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                try:
                    tasks = json.loads(match.group())
                except json.JSONDecodeError:
                    raise DecompositionError(f"Could not parse JSON response: {e}")
            else:
                raise DecompositionError(f"No valid JSON array in response: {e}")
        
        if not isinstance(tasks, list):
            raise DecompositionError(f"Expected list of tasks, got {type(tasks)}")
        
        return tasks
    
    def _validate_tasks(self, tasks: list[dict]) -> None:
        """Validate task structure and dependencies."""
        task_ids = {t.get("task_id") for t in tasks}
        
        for task in tasks:
            # Check required fields
            required = ["task_id", "name", "dependencies", "acceptance_criteria"]
            missing = [f for f in required if f not in task]
            if missing:
                raise DecompositionError(
                    f"Task {task.get('task_id', '?')} missing required fields: {missing}"
                )
            
            # Check dependency references
            for dep in task.get("dependencies", []):
                if dep not in task_ids:
                    raise DecompositionError(
                        f"Task {task['task_id']} references unknown dependency: {dep}"
                    )
            
            # Ensure acceptance_criteria is a list
            if not isinstance(task.get("acceptance_criteria"), list):
                task["acceptance_criteria"] = [task["acceptance_criteria"]]
            
            # Set defaults for optional fields
            task.setdefault("estimated_sessions", 1)
            task.setdefault("files_to_create", [])
            task.setdefault("files_to_modify", [])
            task.setdefault("requires_human", False)
            task.setdefault("human_action", None)


def decompose_goal(
    goal: str,
    api_key: Optional[str] = None,
    context: Optional[str] = None,
    model: str = MODEL_OPUS,
    return_dicts: bool = False,
) -> list[Task]:
    """Convenience function to decompose a goal.
    
    Args:
        goal: Natural language goal description.
        api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var).
        context: Optional additional context.
        model: Model to use (default: Opus 4.5).
        return_dicts: If True, return list[dict] for backward compatibility.
    
    Returns:
        List of Task models (or dicts if return_dicts=True).
    
    Example:
        >>> tasks = decompose_goal("Build a REST API for user management")
        >>> for t in tasks:
        ...     print(f"{t.task_id}: {t.name}")
        T1: Set up project structure
        T2: Implement user model
        T3: Create user endpoints
        ...
    """
    decomposer = GoalDecomposer(api_key=api_key, model=model)
    return decomposer.decompose(goal, context=context, return_dicts=return_dicts)


# CLI support for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python decomposer.py 'Your goal here'")
        print("Set ANTHROPIC_API_KEY environment variable first.")
        sys.exit(1)
    
    goal = " ".join(sys.argv[1:])
    
    try:
        tasks = decompose_goal(goal)
        # Convert to dicts for JSON output
        output = [
            {
                "task_id": t.task_id,
                "name": t.name,
                "dependencies": t.dependencies,
                "acceptance_criteria": t.acceptance_criteria,
                "estimated_sessions": t.estimated_sessions,
                "files_to_create": t.files_to_create,
            }
            for t in tasks
        ]
        print(json.dumps(output, indent=2))
    except DecompositionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
