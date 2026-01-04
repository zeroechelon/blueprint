"""Interface Inference Engine.

Infers input/output contracts for decomposed tasks, ensuring
type compatibility across the task dependency graph.

Part of Blueprint Tier 2: Generator Core.

Design Principles:
- Interface contracts define data flow between tasks
- Outputs of dependencies must match inputs of dependents
- File paths and function signatures are concrete
- Uses Claude for intelligent inference when needed

Changes (P0 Hardening):
- Added tenacity retry with exponential backoff for LLM calls
- Accepts list[Task] or list[dict] for flexibility
"""
import json
import os
from typing import Optional, Union

from anthropic import Anthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from blueprint.models import Task, Interface

# Model hierarchy
MODEL_OPUS = "claude-opus-4-5-20251101"
MODEL_SONNET = "claude-sonnet-4-5-20250929"

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 1  # seconds
RETRY_MAX_WAIT = 30  # seconds


class InferenceError(Exception):
    """Raised when interface inference fails."""
    pass


class InterfaceInferrer:
    """Infers interface contracts for task chains.
    
    Takes a list of decomposed tasks and enriches them with:
    - Concrete input/output type definitions
    - File paths and function signatures
    - Data schema definitions where applicable
    
    Example:
        >>> inferrer = InterfaceInferrer()
        >>> enriched = inferrer.infer(tasks)
        >>> print(enriched[0].interface.output)
        "ProjectConfig dataclass"
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = MODEL_SONNET,  # Sonnet is sufficient for inference
    ):
        """Initialize the inferrer.
        
        Args:
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            model: Model to use. Defaults to Sonnet 4.5 (faster/cheaper).
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise InferenceError(
                "ANTHROPIC_API_KEY not provided. Set environment variable or pass api_key parameter."
            )
        
        self.client = Anthropic(api_key=self.api_key)
        self.model = model
    
    def infer(
        self,
        tasks: Union[list[Task], list[dict]],
        project_context: Optional[str] = None,
    ) -> list[Task]:
        """Infer interface contracts for all tasks.
        
        Args:
            tasks: List of Task models or dicts from GoalDecomposer.
            project_context: Optional context about the project (tech stack, etc).
        
        Returns:
            Tasks enriched with interface contracts (as Task models).
        
        Raises:
            InferenceError: If inference fails after retries.
        """
        # Normalize to dicts for processing
        task_dicts = self._normalize_to_dicts(tasks)
        
        # Build dependency map for context
        dep_map = self._build_dependency_map(task_dicts)
        
        # First pass: infer interfaces using LLM with retry
        prompt = self._build_prompt(task_dicts, project_context)
        interfaces = self._call_llm_with_retry(prompt)
        
        # Merge interfaces into tasks
        enriched_dicts = self._merge_interfaces(task_dicts, interfaces)
        
        # Validate compatibility
        self._validate_compatibility(enriched_dicts, dep_map)
        
        # Convert back to Task models
        return self._convert_to_models(enriched_dicts)
    
    def _normalize_to_dicts(self, tasks: Union[list[Task], list[dict]]) -> list[dict]:
        """Convert Task models to dicts if needed."""
        if not tasks:
            return []
        
        if isinstance(tasks[0], Task):
            return [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "description": t.notes or "",
                    "dependencies": t.dependencies,
                    "files_to_create": t.files_to_create,
                    "files_to_modify": t.files_to_modify,
                    "acceptance_criteria": t.acceptance_criteria,
                    "estimated_sessions": t.estimated_sessions,
                }
                for t in tasks
            ]
        return tasks
    
    def _convert_to_models(self, task_dicts: list[dict]) -> list[Task]:
        """Convert enriched dicts back to Task models."""
        tasks = []
        for raw in task_dicts:
            # Build Interface
            interface = None
            if "interface" in raw:
                interface = Interface(
                    input=raw["interface"].get("input", ""),
                    output=raw["interface"].get("output", ""),
                )
            
            task = Task(
                task_id=raw["task_id"],
                name=raw["name"],
                dependencies=raw.get("dependencies", []),
                interface=interface,
                acceptance_criteria=raw.get("acceptance_criteria", []),
                estimated_sessions=raw.get("estimated_sessions"),
                files_to_create=raw.get("files_to_create", []),
                files_to_modify=raw.get("files_to_modify", []),
                notes=raw.get("description"),
            )
            tasks.append(task)
        
        return tasks
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def _call_llm_with_retry(self, prompt: str) -> dict:
        """Call LLM with automatic retry on failure."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            
            content = response.content[0].text
            return self._parse_response(content)
            
        except Exception as e:
            raise InferenceError(f"LLM call failed: {e}") from e
    
    def _build_dependency_map(self, tasks: list[dict]) -> dict[str, list[str]]:
        """Build map of task_id -> list of dependent task_ids."""
        dep_map = {t["task_id"]: [] for t in tasks}
        
        for task in tasks:
            for dep in task.get("dependencies", []):
                if dep in dep_map:
                    dep_map[dep].append(task["task_id"])
        
        return dep_map
    
    def _build_prompt(
        self,
        tasks: list[dict],
        project_context: Optional[str],
    ) -> str:
        """Build the interface inference prompt."""
        
        context_section = ""
        if project_context:
            context_section = f"""
## Project Context
{project_context}
"""
        
        # Format tasks for prompt
        task_list = []
        for t in tasks:
            deps = ", ".join(t.get("dependencies", [])) or "none"
            files = ", ".join(t.get("files_to_create", [])) or "none"
            task_list.append(
                f"- {t['task_id']}: {t['name']}\n"
                f"  Dependencies: {deps}\n"
                f"  Files: {files}\n"
                f"  Description: {t.get('description', 'N/A')}"
            )
        
        tasks_formatted = "\n".join(task_list)
        
        return f"""You are a software architect defining interface contracts for a task dependency graph.

## Tasks
{tasks_formatted}
{context_section}
## Requirements

For each task, define concrete interface contracts:

1. **Input**: What data/state this task requires from its dependencies
   - For tasks with no dependencies: "None (entry point)" or specific initial state
   - Reference outputs from specific dependency task_ids

2. **Output**: What this task produces for dependent tasks
   - Be specific: data types, file paths, class names
   - Use Python type hints style (e.g., `List[dict]`, `Path`, `UserModel`)

3. **Data Schema**: If the task produces structured data, define the schema
   - Use TypedDict or dataclass style definitions
   - Include field names and types

## Output Format

Return a JSON object mapping task_id to interface:

```json
{{
  "T1": {{
    "input": "None (entry point)",
    "output": "ProjectConfig dataclass with paths and settings",
    "output_type": "ProjectConfig",
    "data_schema": {{
      "ProjectConfig": {{
        "root_path": "Path",
        "src_dir": "Path",
        "test_dir": "Path",
        "dependencies": "List[str]"
      }}
    }}
  }},
  "T2": {{
    "input": "ProjectConfig from T1",
    "output": "CSVReader class in src/reader.py",
    "output_type": "CSVReader",
    "data_schema": null
  }}
}}
```

**Rules**:
- Every task must have input and output defined
- Outputs must be consumable by dependent tasks
- Use concrete types, not vague descriptions
- data_schema is optional, only for complex data structures

Return ONLY the JSON object, no markdown fencing, no explanation."""

    def _parse_response(self, content: str) -> dict:
        """Parse Claude's response into interface map."""
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        
        try:
            interfaces = json.loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON object
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    interfaces = json.loads(match.group())
                except json.JSONDecodeError:
                    raise InferenceError(f"Could not parse JSON response: {e}")
            else:
                raise InferenceError(f"No valid JSON object in response: {e}")
        
        if not isinstance(interfaces, dict):
            raise InferenceError(f"Expected dict of interfaces, got {type(interfaces)}")
        
        return interfaces
    
    def _merge_interfaces(
        self,
        tasks: list[dict],
        interfaces: dict,
    ) -> list[dict]:
        """Merge inferred interfaces into task objects."""
        enriched = []
        
        for task in tasks:
            task_copy = task.copy()
            task_id = task["task_id"]
            
            if task_id in interfaces:
                iface = interfaces[task_id]
                task_copy["interface"] = {
                    "input": iface.get("input", "Unknown"),
                    "output": iface.get("output", "Unknown"),
                }
                if iface.get("output_type"):
                    task_copy["interface"]["output_type"] = iface["output_type"]
                if iface.get("data_schema"):
                    task_copy["interface"]["data_schema"] = iface["data_schema"]
            else:
                # Default interface if not inferred
                task_copy["interface"] = {
                    "input": "See dependencies" if task.get("dependencies") else "None",
                    "output": "Task completion",
                }
            
            enriched.append(task_copy)
        
        return enriched
    
    def _validate_compatibility(
        self,
        tasks: list[dict],
        dep_map: dict[str, list[str]],
    ) -> list[str]:
        """Validate interface compatibility across dependencies.
        
        Returns list of warnings (not errors, to allow flexibility).
        """
        warnings = []
        task_map = {t["task_id"]: t for t in tasks}
        
        for task in tasks:
            task_id = task["task_id"]
            task_input = task.get("interface", {}).get("input", "")
            
            # Check if input references dependencies
            for dep_id in task.get("dependencies", []):
                if dep_id in task_map:
                    dep_output = task_map[dep_id].get("interface", {}).get("output", "")
                    
                    # Simple heuristic: check if dependency is mentioned in input
                    if dep_id not in task_input and dep_output:
                        warnings.append(
                            f"Task {task_id} depends on {dep_id} but input doesn't reference it"
                        )
        
        return warnings


def infer_interfaces(
    tasks: Union[list[Task], list[dict]],
    api_key: Optional[str] = None,
    project_context: Optional[str] = None,
    model: str = MODEL_SONNET,
) -> list[Task]:
    """Convenience function to infer interfaces for tasks.
    
    Args:
        tasks: List of Task models or dicts.
        api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var).
        project_context: Optional project context.
        model: Model to use (default: Sonnet 4.5).
    
    Returns:
        Tasks enriched with interface contracts (as Task models).
    
    Example:
        >>> from blueprint.generator import decompose_goal
        >>> tasks = decompose_goal("Build a REST API")
        >>> enriched = infer_interfaces(tasks)
        >>> print(enriched[0].interface.output)
        "ProjectConfig dataclass"
    """
    inferrer = InterfaceInferrer(api_key=api_key, model=model)
    return inferrer.infer(tasks, project_context=project_context)


# CLI support for testing
if __name__ == "__main__":
    import sys
    
    # Example usage with sample tasks
    sample_tasks = [
        {
            "task_id": "T1",
            "name": "Project setup",
            "description": "Initialize project structure",
            "dependencies": [],
            "files_to_create": ["pyproject.toml", "src/__init__.py"],
        },
        {
            "task_id": "T2", 
            "name": "Core module",
            "description": "Implement main functionality",
            "dependencies": ["T1"],
            "files_to_create": ["src/core.py"],
        },
        {
            "task_id": "T3",
            "name": "CLI interface",
            "description": "Add command line interface",
            "dependencies": ["T2"],
            "files_to_create": ["src/cli.py"],
        },
    ]
    
    try:
        enriched = infer_interfaces(sample_tasks)
        output = [
            {
                "task_id": t.task_id,
                "name": t.name,
                "interface": {
                    "input": t.interface.input if t.interface else "",
                    "output": t.interface.output if t.interface else "",
                }
            }
            for t in enriched
        ]
        print(json.dumps(output, indent=2))
    except InferenceError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
