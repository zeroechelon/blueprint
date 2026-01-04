"""Tests for the goal decomposer.

These tests verify the decomposer can break down goals into atomic tasks
with proper structure and dependencies.
"""
import os
import pytest
from unittest.mock import Mock, patch

from blueprint.generator.decomposer import (
    GoalDecomposer,
    decompose_goal,
    DecompositionError,
    MODEL_OPUS,
    MODEL_SONNET,
)


class TestGoalDecomposer:
    """Test suite for GoalDecomposer class."""
    
    def test_init_requires_api_key(self):
        """Should raise error if no API key provided."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing key
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(DecompositionError, match="ANTHROPIC_API_KEY"):
                GoalDecomposer()
    
    def test_init_accepts_env_var(self):
        """Should accept API key from environment variable."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("blueprint.generator.decomposer.Anthropic"):
                decomposer = GoalDecomposer()
                assert decomposer.api_key == "test-key"
    
    def test_init_accepts_direct_key(self):
        """Should accept API key passed directly."""
        with patch("blueprint.generator.decomposer.Anthropic"):
            decomposer = GoalDecomposer(api_key="direct-key")
            assert decomposer.api_key == "direct-key"
    
    def test_default_model_is_opus(self):
        """Should default to Opus 4.5 model."""
        with patch("blueprint.generator.decomposer.Anthropic"):
            decomposer = GoalDecomposer(api_key="test")
            assert decomposer.model == MODEL_OPUS
    
    def test_parse_response_extracts_json(self):
        """Should extract JSON array from response."""
        decomposer = GoalDecomposer.__new__(GoalDecomposer)
        decomposer.api_key = "test"
        
        response = '[{"task_id": "T1", "name": "Test"}]'
        result = decomposer._parse_response(response)
        
        assert len(result) == 1
        assert result[0]["task_id"] == "T1"
    
    def test_parse_response_handles_markdown_fencing(self):
        """Should handle response wrapped in markdown code blocks."""
        decomposer = GoalDecomposer.__new__(GoalDecomposer)
        decomposer.api_key = "test"
        
        response = '```json\n[{"task_id": "T1", "name": "Test"}]\n```'
        result = decomposer._parse_response(response)
        
        assert len(result) == 1
        assert result[0]["task_id"] == "T1"
    
    def test_validate_tasks_checks_required_fields(self):
        """Should validate that required fields are present."""
        decomposer = GoalDecomposer.__new__(GoalDecomposer)
        
        tasks = [{"task_id": "T1"}]  # Missing name, dependencies, acceptance_criteria
        
        with pytest.raises(DecompositionError, match="missing required fields"):
            decomposer._validate_tasks(tasks)
    
    def test_validate_tasks_checks_dependencies(self):
        """Should validate that dependencies reference existing tasks."""
        decomposer = GoalDecomposer.__new__(GoalDecomposer)
        
        tasks = [{
            "task_id": "T1",
            "name": "Test",
            "dependencies": ["T99"],  # Non-existent
            "acceptance_criteria": ["Done"]
        }]
        
        with pytest.raises(DecompositionError, match="unknown dependency"):
            decomposer._validate_tasks(tasks)
    
    def test_validate_tasks_sets_defaults(self):
        """Should set default values for optional fields."""
        decomposer = GoalDecomposer.__new__(GoalDecomposer)
        
        tasks = [{
            "task_id": "T1",
            "name": "Test",
            "dependencies": [],
            "acceptance_criteria": ["Done"]
        }]
        
        decomposer._validate_tasks(tasks)
        
        assert tasks[0]["estimated_sessions"] == 1
        assert tasks[0]["files_to_create"] == []
        assert tasks[0]["files_to_modify"] == []
        assert tasks[0]["requires_human"] is False


class TestDecomposeGoalFunction:
    """Test suite for convenience function."""
    
    def test_decompose_goal_creates_decomposer(self):
        """Should create decomposer and call decompose."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text='[{"task_id": "T1", "name": "Test", "dependencies": [], "acceptance_criteria": ["Done"]}]')]
        mock_client.messages.create.return_value = mock_response
        
        with patch("blueprint.generator.decomposer.Anthropic", return_value=mock_client):
            tasks = decompose_goal("Test goal", api_key="test-key")
        
        assert len(tasks) == 1
        assert tasks[0].task_id == "T1"


# Integration test - only runs if API key is available
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
class TestDecomposerIntegration:
    """Integration tests that require actual API access."""
    
    def test_real_decomposition(self):
        """Test actual decomposition with Claude API."""
        tasks = decompose_goal(
            "Build a simple hello world CLI in Python",
            model=MODEL_SONNET,  # Use Sonnet for faster/cheaper tests
        )
        
        assert len(tasks) >= 2
        assert all(hasattr(t, "task_id") for t in tasks)
        assert all(hasattr(t, "name") for t in tasks)
        assert all(hasattr(t, "dependencies") for t in tasks)

