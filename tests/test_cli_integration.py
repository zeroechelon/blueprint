"""Integration tests for the Blueprint CLI.

These tests verify CLI commands work with real Blueprint files.
"""
import json
import os
import tempfile
from pathlib import Path
import pytest

from blueprint.cli import main, cmd_parse, cmd_validate


# Sample Blueprint in JSON format
SAMPLE_JSON = {
    "blueprint_version": "0.1.0",
    "metadata": {
        "title": "Test Blueprint",
        "status": "draft",
        "created": "2026-01-03",
        "owner": "Test"
    },
    "strategic_vision": "Test project",
    "success_metrics": [],
    "tiers": [
        {
            "tier_id": "T0",
            "name": "Foundation",
            "goal": "Setup",
            "status": "not_started",
            "tasks": [
                {
                    "task_id": "T0.1",
                    "name": "Init project",
                    "status": "not_started",
                    "dependencies": [],
                    "interface": {"input": "None", "output": "Project"},
                    "acceptance_criteria": ["Project exists"],
                    "test_command": "echo ok",
                    "rollback": "rm -rf ."
                }
            ]
        }
    ],
    "dependency_graph": {"nodes": ["T0.1"], "edges": []},
    "document_control": {"version": "0.1", "history": []}
}

# Sample Blueprint in Markdown format
SAMPLE_MARKDOWN = """# Test Project — Blueprint

> **Document Status**: Draft
> **Last Updated**: 2026-01-03
> **Owner**: Test User

---

## Strategic Vision

A test project.

---

## Tier 0: Foundation

**Goal**: Setup

### T0.1: Init Project

```yaml
task_id: T0.1
name: "Initialize project"
status: 🔲 NOT_STARTED
dependencies: []

interface:
  input: "None"
  output: "Project"

acceptance_criteria:
  - Project exists

test_command: "echo ok"
rollback: "rm -rf ."
```

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-01-03 | Test | Initial |
"""


@pytest.fixture
def json_blueprint_file(tmp_path):
    """Create a temporary JSON Blueprint file."""
    filepath = tmp_path / "test.json"
    filepath.write_text(json.dumps(SAMPLE_JSON, indent=2))
    return filepath


@pytest.fixture
def md_blueprint_file(tmp_path):
    """Create a temporary Markdown Blueprint file."""
    filepath = tmp_path / "test.md"
    filepath.write_text(SAMPLE_MARKDOWN)
    return filepath


class TestParseCommand:
    """Test 'blueprint parse' command."""
    
    def test_parse_json_file(self, json_blueprint_file, capsys):
        """Should parse JSON Blueprint and show structure."""
        result = main(["parse", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "Test Blueprint" in captured.out
        assert "Tiers:" in captured.out
        assert "T0.1" in captured.out
    
    def test_parse_markdown_file(self, md_blueprint_file, capsys):
        """Should parse Markdown Blueprint and show structure."""
        result = main(["parse", str(md_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        # Check for tier/task output
        assert "T0" in captured.out or "Foundation" in captured.out
    
    def test_parse_nonexistent_file(self, capsys):
        """Should fail gracefully for missing file."""
        result = main(["parse", "/nonexistent/path.md"])
        assert result == 1
        
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()
    
    def test_parse_verbose(self, json_blueprint_file, capsys):
        """Should show more detail with --verbose."""
        result = main(["parse", "-v", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        # Verbose should show interface info
        assert "Input:" in captured.out or "Output:" in captured.out


class TestValidateCommand:
    """Test 'blueprint validate' command."""
    
    def test_validate_valid_json(self, json_blueprint_file, capsys):
        """Should validate correct JSON Blueprint."""
        result = main(["validate", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "✅" in captured.out or "valid" in captured.out.lower()
    
    def test_validate_valid_markdown(self, md_blueprint_file, capsys):
        """Should validate correct Markdown Blueprint."""
        result = main(["validate", str(md_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "✅" in captured.out or "valid" in captured.out.lower()
    
    def test_validate_shows_task_count(self, json_blueprint_file, capsys):
        """Should show task count on success."""
        result = main(["validate", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "Tasks:" in captured.out


class TestExecuteCommand:
    """Test 'blueprint execute' command."""
    
    def test_execute_dry_run(self, json_blueprint_file, capsys):
        """Should execute in dry-run mode by default."""
        result = main(["execute", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out or "simulated" in captured.out.lower()
    
    def test_execute_shows_results(self, json_blueprint_file, capsys):
        """Should show execution results."""
        result = main(["execute", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "Completed:" in captured.out


class TestGenerateCommand:
    """Test 'blueprint generate' command."""
    
    def test_generate_requires_goal(self, capsys):
        """Should fail without goal argument."""
        result = main(["generate"])
        assert result == 1
        
        captured = capsys.readouterr()
        assert "requires" in captured.err.lower() or "goal" in captured.err.lower()
    
    def test_generate_without_api_key(self, capsys, monkeypatch):
        """Should fail gracefully without API key."""
        # Remove API key if set
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        
        result = main(["generate", "Build a simple calculator"])
        # Should fail because no API key
        assert result == 1
        
        captured = capsys.readouterr()
        assert "api" in captured.err.lower() or "key" in captured.err.lower() or "error" in captured.err.lower()


class TestOutputOption:
    """Test -o/--output option for generate."""
    
    def test_generate_output_option_parsed(self, capsys, monkeypatch):
        """Should parse -o option correctly."""
        # Just verify option is accepted (will fail on API key)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        
        result = main(["generate", "Test goal", "-o", "/tmp/test.md"])
        # Will fail but should parse args correctly
        assert result == 1


class TestVerboseFlag:
    """Test --verbose flag across commands."""
    
    def test_validate_verbose(self, json_blueprint_file, capsys):
        """Should show extra info with --verbose."""
        result = main(["validate", "--verbose", str(json_blueprint_file)])
        assert result == 0
        
        captured = capsys.readouterr()
        assert "Warnings:" in captured.out
