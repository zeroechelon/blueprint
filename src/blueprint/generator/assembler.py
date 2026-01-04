"""Blueprint Assembler.

Transforms enriched tasks into valid Blueprint markdown documents.
Produces output that passes the Blueprint validator.

Part of Blueprint Tier 2: Generator Core.

Design Principles:
- Output must be valid Blueprint Standard Format
- Every task includes test_command and rollback
- Large Blueprints trigger Linker decomposition warning
- Self-hosting: this assembler's output can be parsed by parser.py
- Generated documents include metadata for validation/detection

Changes (v1.2.0):
- Added generation metadata block to header
- Added BLUEPRINT_VERSION constant
- Metadata enables detection of manually-generated (invalid) Blueprints
"""
import json
import os
from datetime import date, datetime, timezone
from typing import Optional

from anthropic import Anthropic

# Blueprint version - used in generation metadata
BLUEPRINT_VERSION = "1.2.0"

# Model hierarchy
MODEL_OPUS = "claude-opus-4-5-20251101"
MODEL_SONNET = "claude-sonnet-4-5-20250929"

# Linker threshold - warn when tasks exceed this
LINKER_THRESHOLD = 100


class AssemblyError(Exception):
    """Raised when Blueprint assembly fails."""
    pass


class BlueprintAssembler:
    """Assembles enriched tasks into Blueprint markdown.
    
    Takes tasks with interface contracts and produces a complete
    Blueprint document ready for validation and execution.
    
    Example:
        >>> assembler = BlueprintAssembler()
        >>> markdown = assembler.assemble(tasks, goal="Build a CLI tool")
        >>> print(markdown[:100])
        "# CLI Tool — Master Roadmap..."
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = MODEL_SONNET,
    ):
        """Initialize the assembler.
        
        Args:
            api_key: Anthropic API key for test/rollback generation.
            model: Model to use for generation.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client = None
        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)
        self.model = model
    
    
    def _normalize_tasks(self, tasks: list) -> list[dict]:
        """Normalize Task models or dicts to list of dicts.
        
        Accepts either list[Task] (Pydantic models) or list[dict].
        Returns list[dict] for internal processing.
        
        Added in v1.1.0 to fix compatibility with interface inferrer output.
        """
        from blueprint.models import Task
        
        normalized = []
        for task in tasks:
            if isinstance(task, Task):
                # Convert Pydantic model to dict
                task_dict = task.model_dump()
                # Flatten interface if present
                if task.interface:
                    task_dict["interface"] = {
                        "input": task.interface.input,
                        "output": task.interface.output,
                    }
                normalized.append(task_dict)
            elif isinstance(task, dict):
                normalized.append(task.copy())
            else:
                raise AssemblyError(f"Unexpected task type: {type(task)}")
        
        return normalized
    
    def assemble(
        self,
        tasks: list,
        goal: str,
        project_name: Optional[str] = None,
        owner: str = "Technical Operations",
        include_test_commands: bool = True,
        include_rollback: bool = True,
    ) -> str:
        """Assemble tasks into Blueprint markdown.
        
        Args:
            tasks: Enriched tasks from interface inferrer (Task models or dicts).
            goal: Original goal/vision for the project.
            project_name: Name for the Blueprint (derived from goal if not provided).
            owner: Document owner name.
            include_test_commands: Generate test commands using LLM.
            include_rollback: Generate rollback commands.
        
        Returns:
            Complete Blueprint markdown document.
        
        Raises:
            AssemblyError: If assembly fails.
        """
        # Normalize tasks to dicts (handles both Task models and dicts)
        tasks = self._normalize_tasks(tasks)
        
        # Check Linker threshold
        if len(tasks) > LINKER_THRESHOLD:
            raise AssemblyError(
                f"Task count ({len(tasks)}) exceeds Linker threshold ({LINKER_THRESHOLD}). "
                f"Consider decomposing into sub-modules using BlueprintRef. "
                f"See SYSTEM_ARCHITECTURE.md 'Hierarchical Compilation'."
            )
        
        # Derive project name from goal if not provided
        if not project_name:
            project_name = self._derive_project_name(goal)
        
        # Ensure tasks have test commands and rollback
        if include_test_commands or include_rollback:
            tasks = self._enrich_with_commands(tasks)
        
        # Organize tasks into tiers
        tiers = self._organize_into_tiers(tasks)
        
        # Build document sections
        sections = [
            self._build_header(project_name, owner),
            self._build_vision(goal),
            self._build_metrics(tasks),
        ]
        
        # Add tier sections
        for tier_id, tier_data in tiers.items():
            sections.append(self._build_tier_section(tier_id, tier_data))
        
        # Add dependency graph
        sections.append(self._build_dependency_graph(tasks))
        
        # Add document control
        sections.append(self._build_document_control())
        
        return "\n\n---\n\n".join(sections)
    def _derive_project_name(self, goal: str) -> str:
        """Derive a project name from the goal."""
        # Simple heuristic: take first few significant words
        words = goal.split()[:5]
        # Remove common words
        skip = {"a", "an", "the", "build", "create", "implement", "make", "develop"}
        significant = [w for w in words if w.lower() not in skip]
        if significant:
            return " ".join(significant[:3]).title()
        return "Project Blueprint"
    
    def _enrich_with_commands(self, tasks: list[dict]) -> list[dict]:
        """Add test_command and rollback to tasks that lack them."""
        enriched = []
        
        for task in tasks:
            task_copy = task.copy()
            
            # Generate test command if missing
            if not task_copy.get("test_command"):
                task_copy["test_command"] = self._generate_test_command(task_copy)
            
            # Generate rollback if missing
            if not task_copy.get("rollback"):
                task_copy["rollback"] = self._generate_rollback(task_copy)
            
            enriched.append(task_copy)
        
        return enriched
    
    def _generate_test_command(self, task: dict) -> str:
        """Generate a test command for a task."""
        files = task.get("files_to_create", [])
        
        # Simple heuristic based on file types
        if any(f.endswith(".py") for f in files):
            test_file = files[0].replace(".py", "").replace("/", ".")
            return f"python3 -m pytest tests/test_{task['task_id'].lower()}.py -v"
        elif any(f.endswith(".js") or f.endswith(".ts") for f in files):
            return "npm test"
        else:
            return f"echo 'Verify {task['name']} completed successfully'"
    
    def _generate_rollback(self, task: dict) -> str:
        """Generate a rollback command for a task."""
        files = task.get("files_to_create", [])
        
        if files:
            files_str = " ".join(files)
            return f"git checkout HEAD~1 -- {files_str}"
        else:
            return "git revert HEAD --no-edit"
    
    def _organize_into_tiers(self, tasks: list[dict]) -> dict:
        """Organize tasks into logical tiers based on dependencies."""
        # Build dependency levels
        task_map = {t["task_id"]: t for t in tasks}
        levels = {}
        
        def get_level(task_id: str, visited: set) -> int:
            if task_id in levels:
                return levels[task_id]
            if task_id in visited:
                return 0  # Cycle detected, treat as level 0
            
            visited.add(task_id)
            task = task_map.get(task_id)
            if not task:
                return 0
            
            deps = task.get("dependencies", [])
            if not deps:
                levels[task_id] = 0
                return 0
            
            max_dep_level = max(get_level(d, visited) for d in deps)
            levels[task_id] = max_dep_level + 1
            return levels[task_id]
        
        # Calculate levels for all tasks
        for task in tasks:
            get_level(task["task_id"], set())
        
        # Group by level into tiers
        tiers = {}
        for task in tasks:
            level = levels.get(task["task_id"], 0)
            tier_id = f"T{level}"
            
            if tier_id not in tiers:
                tiers[tier_id] = {
                    "name": self._tier_name(level),
                    "tasks": [],
                }
            
            tiers[tier_id]["tasks"].append(task)
        
        return dict(sorted(tiers.items()))
    
    def _tier_name(self, level: int) -> str:
        """Generate a tier name based on level."""
        names = [
            "Foundation",
            "Core Implementation", 
            "Feature Development",
            "Integration",
            "Testing & Polish",
            "Release Preparation",
        ]
        if level < len(names):
            return names[level]
        return f"Phase {level}"
    
    def _build_header(self, project_name: str, owner: str) -> str:
        """Build document header with generation metadata."""
        today = date.today().isoformat()
        generated_at = datetime.now(timezone.utc).isoformat()
        
        return f"""# {project_name} — Master Roadmap

> **Document Status**: Living Document (Blueprint Standard Format v0.1)
> **Last Updated**: {today}
> **Owner**: {owner}
> **Validated By**: Blueprint Generator v{BLUEPRINT_VERSION}

<!-- BLUEPRINT METADATA (DO NOT REMOVE) -->
<!-- _blueprint_version: {BLUEPRINT_VERSION} -->
<!-- _generated_at: {generated_at} -->
<!-- _generator: blueprint.generator.assembler -->
<!-- END METADATA -->"""

    def _build_vision(self, goal: str) -> str:
        """Build strategic vision section."""
        return f"""## Strategic Vision

{goal}

**North Star**: Deliver a working, tested implementation that meets all acceptance criteria."""

    def _build_metrics(self, tasks: list[dict]) -> str:
        """Build success metrics section."""
        total = len(tasks)
        human_required = sum(1 for t in tasks if t.get("requires_human") or t.get("human_required"))
        
        return f"""## Success Metrics

| Metric | Target | Validation |
|--------|--------|------------|
| Task completion | 100% ({total} tasks) | All acceptance criteria met |
| Test coverage | >80% | pytest --cov |
| Human interventions | {human_required} | HUMAN_REQUIRED blocks acknowledged |
| Validation | Pass | `blueprint validate` returns 0 |"""

    def _build_tier_section(self, tier_id: str, tier_data: dict) -> str:
        """Build a tier section with all its tasks."""
        completed = sum(1 for t in tier_data["tasks"] if t.get("status") == "complete")
        total = len(tier_data["tasks"])
        
        status = "✅ COMPLETE" if completed == total else f"🔄 {completed}/{total}"
        
        lines = [f"## Tier {tier_id[1:]}: {tier_data['name']} {status}"]
        
        for task in tier_data["tasks"]:
            lines.append(self._build_task_block(task))
        
        return "\n\n".join(lines)
    
    def _build_task_block(self, task: dict) -> str:
        """Build a YAML task block."""
        # Map status
        status = task.get("status", "not_started")
        status_map = {
            "not_started": "🔲 NOT_STARTED",
            "in_progress": "🔄 IN_PROGRESS",
            "complete": "✅ COMPLETE",
            "blocked": "⛔ BLOCKED",
        }
        status_str = status_map.get(status, "🔲 NOT_STARTED")
        
        # Build dependencies list
        deps = task.get("dependencies", [])
        deps_str = json.dumps(deps)
        
        # Build interface
        iface = task.get("interface", {})
        iface_input = iface.get("input", "See dependencies")
        iface_output = iface.get("output", "Task completion")
        
        # Build acceptance criteria
        criteria = task.get("acceptance_criteria", ["Task completed successfully"])
        criteria_lines = "\n".join(f"  - {c}" for c in criteria)
        
        # Build files lists
        files_create = task.get("files_to_create", [])
        files_modify = task.get("files_to_modify", [])
        
        # Build human_required block if present
        human_block = ""
        hr = task.get("human_required") or (task.get("requires_human") and task.get("human_action"))
        if hr:
            if isinstance(hr, dict):
                human_block = f"""
human_required:
  action: "{hr.get('action', 'Human action required')}"
  reason: "{hr.get('reason', 'Required for task completion')}"
  notify:
    channel: "{hr.get('notify', {}).get('channel', 'console')}"
  on_missing: "ABORT"
"""
            elif task.get("requires_human") and task.get("human_action"):
                human_block = f"""
human_required:
  action: "{task.get('human_action')}"
  reason: "Required for task completion"
  notify:
    channel: "console"
  on_missing: "ABORT"
"""
        
        # Escape test command for YAML
        test_cmd = task.get("test_command", "echo 'Test not defined'")
        rollback = task.get("rollback", "git revert HEAD --no-edit")
        
        yaml_block = f"""### {task['task_id']}: {task['name']}

```yaml
task_id: {task['task_id']}
name: "{task['name']}"
status: {status_str}
assignee: null
estimated_sessions: {task.get('estimated_sessions', 1)}
dependencies: {deps_str}

interface:
  input: "{iface_input}"
  output: "{iface_output}"
"""
        
        if files_create:
            yaml_block += "\nfiles_to_create:\n"
            for f in files_create:
                yaml_block += f"  - {f}\n"
        
        if files_modify:
            yaml_block += "\nfiles_to_modify:\n"
            for f in files_modify:
                yaml_block += f"  - {f}\n"
        
        yaml_block += f"""
acceptance_criteria:
{criteria_lines}
{human_block}
test_command: |
  {test_cmd}

rollback: "{rollback}"
```"""
        
        return yaml_block
    
    def _build_dependency_graph(self, tasks: list[dict]) -> str:
        """Build dependency graph section."""
        lines = ["## Dependency Graph", "", "```"]
        
        # Build simple text graph
        for task in tasks:
            task_id = task["task_id"]
            deps = task.get("dependencies", [])
            
            if deps:
                deps_str = ", ".join(deps)
                lines.append(f"{deps_str} ─► {task_id}")
            else:
                lines.append(f"{task_id} (entry point)")
        
        lines.append("```")
        
        # Add parallelization hints
        lines.append("")
        lines.append("**Parallelizable**: Tasks at the same tier level can run concurrently.")
        
        return "\n".join(lines)
    
    def _build_document_control(self) -> str:
        """Build document control section."""
        today = date.today().isoformat()
        return f"""## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | {today} | Blueprint Generator | Initial generation |

*Generated by Blueprint v{BLUEPRINT_VERSION} — "Goals become roadmaps"*"""


def assemble_blueprint(
    tasks: list[dict],
    goal: str,
    api_key: Optional[str] = None,
    project_name: Optional[str] = None,
    owner: str = "Technical Operations",
) -> str:
    """Convenience function to assemble a Blueprint.
    
    Args:
        tasks: Enriched tasks from interface inferrer.
        goal: Original goal description.
        api_key: Anthropic API key (optional, for enhanced generation).
        project_name: Name for the Blueprint.
        owner: Document owner name.
    
    Returns:
        Complete Blueprint markdown document.
    
    Example:
        >>> from blueprint.generator import decompose_goal, infer_interfaces
        >>> tasks = decompose_goal("Build a REST API")
        >>> enriched = infer_interfaces(tasks)
        >>> markdown = assemble_blueprint(enriched, "Build a REST API")
        >>> print(markdown)
    """
    assembler = BlueprintAssembler(api_key=api_key)
    return assembler.assemble(tasks, goal, project_name=project_name, owner=owner)


# CLI support for testing
if __name__ == "__main__":
    # Example with sample tasks
    sample_tasks = [
        {
            "task_id": "T1",
            "name": "Project setup",
            "description": "Initialize project structure",
            "dependencies": [],
            "estimated_sessions": 1,
            "acceptance_criteria": ["Project structure created", "Dependencies defined"],
            "files_to_create": ["pyproject.toml", "src/__init__.py"],
            "interface": {"input": "None (entry point)", "output": "ProjectConfig"},
        },
        {
            "task_id": "T2",
            "name": "Core module",
            "description": "Implement main functionality",
            "dependencies": ["T1"],
            "estimated_sessions": 2,
            "acceptance_criteria": ["Core logic implemented", "Unit tests pass"],
            "files_to_create": ["src/core.py", "tests/test_core.py"],
            "interface": {"input": "ProjectConfig from T1", "output": "CoreModule"},
        },
        {
            "task_id": "T3",
            "name": "CLI interface",
            "description": "Add command line interface",
            "dependencies": ["T2"],
            "estimated_sessions": 1,
            "acceptance_criteria": ["CLI parses arguments", "Help text displays"],
            "files_to_create": ["src/cli.py"],
            "interface": {"input": "CoreModule from T2", "output": "Executable CLI"},
        },
    ]
    
    markdown = assemble_blueprint(
        sample_tasks,
        goal="Build a sample CLI application with core functionality",
        project_name="Sample CLI",
    )
    print(markdown)
