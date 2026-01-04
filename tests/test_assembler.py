"""Tests for the Blueprint assembler.

These tests verify the assembler produces valid Blueprint markdown
that passes the validator.
"""
import os
import pytest
from datetime import date

from blueprint.generator.assembler import (
    BlueprintAssembler,
    assemble_blueprint,
    AssemblyError,
    LINKER_THRESHOLD,
)


class TestBlueprintAssembler:
    """Test suite for BlueprintAssembler class."""
    
    @pytest.fixture
    def sample_tasks(self):
        """Sample enriched tasks for testing."""
        return [
            {
                "task_id": "T1",
                "name": "Project setup",
                "description": "Initialize project",
                "dependencies": [],
                "estimated_sessions": 1,
                "acceptance_criteria": ["Structure created"],
                "files_to_create": ["pyproject.toml"],
                "interface": {"input": "None", "output": "ProjectConfig"},
            },
            {
                "task_id": "T2",
                "name": "Core module",
                "description": "Implement core",
                "dependencies": ["T1"],
                "estimated_sessions": 2,
                "acceptance_criteria": ["Core implemented", "Tests pass"],
                "files_to_create": ["src/core.py"],
                "interface": {"input": "ProjectConfig from T1", "output": "CoreModule"},
            },
        ]
    
    def test_init_without_api_key(self):
        """Should initialize without API key (basic mode)."""
        assembler = BlueprintAssembler()
        assert assembler.client is None or assembler.api_key is not None
    
    def test_derive_project_name(self):
        """Should derive project name from goal."""
        assembler = BlueprintAssembler()
        
        name = assembler._derive_project_name("Build a REST API for users")
        name_lower = name.lower()
        assert "rest" in name_lower or "api" in name_lower or "user" in name_lower
    
    def test_derive_project_name_strips_common_words(self):
        """Should strip common words like 'build', 'create', etc."""
        assembler = BlueprintAssembler()
        
        name = assembler._derive_project_name("Create a simple todo app")
        assert "create" not in name.lower()
        assert "a" not in name.lower().split()
    
    def test_organize_into_tiers(self, sample_tasks):
        """Should organize tasks into tiers based on dependencies."""
        assembler = BlueprintAssembler()
        
        tiers = assembler._organize_into_tiers(sample_tasks)
        
        assert "T0" in tiers  # T1 has no deps, goes to tier 0
        assert "T1" in tiers  # T2 depends on T1, goes to tier 1
        assert sample_tasks[0] in tiers["T0"]["tasks"]
        assert sample_tasks[1] in tiers["T1"]["tasks"]
    
    def test_generate_test_command_python(self, sample_tasks):
        """Should generate pytest command for Python files."""
        assembler = BlueprintAssembler()
        
        task = sample_tasks[1]  # Has .py file
        cmd = assembler._generate_test_command(task)
        
        assert "pytest" in cmd
    
    def test_generate_rollback(self, sample_tasks):
        """Should generate git checkout rollback command."""
        assembler = BlueprintAssembler()
        
        task = sample_tasks[0]
        rollback = assembler._generate_rollback(task)
        
        assert "git checkout" in rollback
        assert "pyproject.toml" in rollback
    
    def test_assemble_produces_markdown(self, sample_tasks):
        """Should produce valid markdown output."""
        assembler = BlueprintAssembler()
        
        markdown = assembler.assemble(sample_tasks, goal="Test project")
        
        assert markdown.startswith("#")
        assert "Strategic Vision" in markdown
        assert "Success Metrics" in markdown
        assert "Dependency Graph" in markdown
    
    def test_assemble_includes_all_tasks(self, sample_tasks):
        """Should include all tasks in output."""
        assembler = BlueprintAssembler()
        
        markdown = assembler.assemble(sample_tasks, goal="Test")
        
        assert "T1:" in markdown
        assert "T2:" in markdown
        assert "Project setup" in markdown
        assert "Core module" in markdown
    
    def test_assemble_includes_yaml_blocks(self, sample_tasks):
        """Should include YAML task blocks."""
        assembler = BlueprintAssembler()
        
        markdown = assembler.assemble(sample_tasks, goal="Test")
        
        assert "```yaml" in markdown
        assert "task_id:" in markdown
        assert "dependencies:" in markdown
        assert "acceptance_criteria:" in markdown
    
    def test_assemble_respects_linker_threshold(self):
        """Should raise error when tasks exceed Linker threshold."""
        assembler = BlueprintAssembler()
        
        # Create many tasks
        many_tasks = [
            {
                "task_id": f"T{i}",
                "name": f"Task {i}",
                "dependencies": [],
                "acceptance_criteria": ["Done"],
            }
            for i in range(LINKER_THRESHOLD + 10)
        ]
        
        with pytest.raises(AssemblyError, match="Linker threshold"):
            assembler.assemble(many_tasks, goal="Too many tasks")
    
    def test_build_header_includes_date(self):
        """Should include current date in header."""
        assembler = BlueprintAssembler()
        
        header = assembler._build_header("Test", "Owner")
        
        assert date.today().isoformat() in header
    
    def test_build_metrics_counts_human_required(self, sample_tasks):
        """Should count tasks with human_required."""
        assembler = BlueprintAssembler()
        
        # Add a human required task
        sample_tasks[0]["requires_human"] = True
        sample_tasks[0]["human_action"] = "Provide API key"
        
        metrics = assembler._build_metrics(sample_tasks)
        
        assert "1" in metrics  # One human intervention


class TestAssembleBlueprintFunction:
    """Test suite for convenience function."""
    
    def test_assemble_blueprint_creates_assembler(self):
        """Should create assembler and call assemble."""
        tasks = [
            {
                "task_id": "T1",
                "name": "Test",
                "dependencies": [],
                "acceptance_criteria": ["Done"],
                "files_to_create": ["test.py"],
                "interface": {"input": "None", "output": "Result"},
            }
        ]
        
        markdown = assemble_blueprint(tasks, goal="Test goal")
        
        assert "# " in markdown  # Has header
        assert "T1:" in markdown
        assert "Test" in markdown


# Integration test - requires full module chain
class TestAssemblerIntegration:
    """Integration tests for assembler with parser and validator."""
    
    def test_output_passes_validator(self):
        """Assembled Blueprint should pass validator."""
        # Import here to avoid circular imports in unit tests
        from blueprint.parser import parse_markdown
        from blueprint.validator import validate
        
        tasks = [
            {
                "task_id": "T1",
                "name": "Setup",
                "dependencies": [],
                "estimated_sessions": 1,
                "acceptance_criteria": ["Project created"],
                "files_to_create": ["setup.py"],
                "interface": {"input": "None", "output": "Config"},
            },
            {
                "task_id": "T2",
                "name": "Build",
                "dependencies": ["T1"],
                "estimated_sessions": 2,
                "acceptance_criteria": ["Built successfully"],
                "files_to_create": ["src/main.py"],
                "interface": {"input": "Config from T1", "output": "App"},
            },
        ]
        
        markdown = assemble_blueprint(tasks, goal="Build test app")
        parsed = parse_markdown(markdown)
        result = validate(parsed)
        
        # Should pass validation (warnings are OK)
        assert result.passed, f"Validation failed: {[str(e) for e in result.errors]}"
