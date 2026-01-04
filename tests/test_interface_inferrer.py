"""Tests for the interface inferrer.

These tests verify the inferrer can enrich tasks with interface contracts
and validate compatibility across the dependency graph.
"""
import os
import pytest
from unittest.mock import Mock, patch

from blueprint.generator.interface_inferrer import (
    InterfaceInferrer,
    infer_interfaces,
    InferenceError,
    MODEL_SONNET,
)


class TestInterfaceInferrer:
    """Test suite for InterfaceInferrer class."""
    
    def test_init_requires_api_key(self):
        """Should raise error if no API key provided."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(InferenceError, match="ANTHROPIC_API_KEY"):
                InterfaceInferrer()
    
    def test_init_accepts_env_var(self):
        """Should accept API key from environment variable."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("blueprint.generator.interface_inferrer.Anthropic"):
                inferrer = InterfaceInferrer()
                assert inferrer.api_key == "test-key"
    
    def test_default_model_is_sonnet(self):
        """Should default to Sonnet 4.5 model (faster for inference)."""
        with patch("blueprint.generator.interface_inferrer.Anthropic"):
            inferrer = InterfaceInferrer(api_key="test")
            assert inferrer.model == MODEL_SONNET
    
    def test_build_dependency_map(self):
        """Should build correct dependency map."""
        inferrer = InterfaceInferrer.__new__(InterfaceInferrer)
        
        tasks = [
            {"task_id": "T1", "dependencies": []},
            {"task_id": "T2", "dependencies": ["T1"]},
            {"task_id": "T3", "dependencies": ["T1", "T2"]},
        ]
        
        dep_map = inferrer._build_dependency_map(tasks)
        
        assert dep_map["T1"] == ["T2", "T3"]
        assert dep_map["T2"] == ["T3"]
        assert dep_map["T3"] == []
    
    def test_parse_response_extracts_json(self):
        """Should extract JSON object from response."""
        inferrer = InterfaceInferrer.__new__(InterfaceInferrer)
        
        response = '{"T1": {"input": "None", "output": "Config"}}'
        result = inferrer._parse_response(response)
        
        assert "T1" in result
        assert result["T1"]["input"] == "None"
    
    def test_parse_response_handles_markdown_fencing(self):
        """Should handle response wrapped in markdown code blocks."""
        inferrer = InterfaceInferrer.__new__(InterfaceInferrer)
        
        response = '```json\n{"T1": {"input": "None", "output": "Config"}}\n```'
        result = inferrer._parse_response(response)
        
        assert "T1" in result
    
    def test_merge_interfaces_enriches_tasks(self):
        """Should merge inferred interfaces into tasks."""
        inferrer = InterfaceInferrer.__new__(InterfaceInferrer)
        
        tasks = [
            {"task_id": "T1", "name": "Setup"},
            {"task_id": "T2", "name": "Build", "dependencies": ["T1"]},
        ]
        
        interfaces = {
            "T1": {"input": "None", "output": "Config", "output_type": "Config"},
            "T2": {"input": "Config from T1", "output": "Result"},
        }
        
        enriched = inferrer._merge_interfaces(tasks, interfaces)
        
        assert enriched[0]["interface"]["input"] == "None"
        assert enriched[0]["interface"]["output"] == "Config"
        assert enriched[0]["interface"]["output_type"] == "Config"
        assert enriched[1]["interface"]["input"] == "Config from T1"
    
    def test_merge_interfaces_handles_missing(self):
        """Should provide default interface for tasks not in inference result."""
        inferrer = InterfaceInferrer.__new__(InterfaceInferrer)
        
        tasks = [
            {"task_id": "T1", "name": "Setup", "dependencies": []},
        ]
        
        interfaces = {}  # Empty - no inference result
        
        enriched = inferrer._merge_interfaces(tasks, interfaces)
        
        assert enriched[0]["interface"]["input"] == "None"
        assert enriched[0]["interface"]["output"] == "Task completion"
    
    def test_validate_compatibility_returns_warnings(self):
        """Should return warnings for potential interface mismatches."""
        inferrer = InterfaceInferrer.__new__(InterfaceInferrer)
        
        tasks = [
            {
                "task_id": "T1",
                "dependencies": [],
                "interface": {"input": "None", "output": "ConfigData"},
            },
            {
                "task_id": "T2",
                "dependencies": ["T1"],
                "interface": {"input": "Something else", "output": "Result"},  # Doesn't mention T1
            },
        ]
        
        dep_map = {"T1": ["T2"], "T2": []}
        warnings = inferrer._validate_compatibility(tasks, dep_map)
        
        assert len(warnings) > 0
        assert "T2" in warnings[0]


class TestInferInterfacesFunction:
    """Test suite for convenience function."""
    
    def test_infer_interfaces_creates_inferrer(self):
        """Should create inferrer and call infer."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text='{"T1": {"input": "None", "output": "Result"}}')]
        mock_client.messages.create.return_value = mock_response
        
        tasks = [{"task_id": "T1", "name": "Test", "dependencies": []}]
        
        with patch("blueprint.generator.interface_inferrer.Anthropic", return_value=mock_client):
            enriched = infer_interfaces(tasks, api_key="test-key")
        
        assert len(enriched) == 1
        assert enriched[0].interface is not None


# Integration test - only runs if API key is available
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
class TestInferrerIntegration:
    """Integration tests that require actual API access."""
    
    def test_real_inference(self):
        """Test actual interface inference with Claude API."""
        tasks = [
            {
                "task_id": "T1",
                "name": "Setup",
                "description": "Initialize project",
                "dependencies": [],
                "files_to_create": ["pyproject.toml"],
            },
            {
                "task_id": "T2",
                "name": "Core",
                "description": "Implement main logic",
                "dependencies": ["T1"],
                "files_to_create": ["src/core.py"],
            },
        ]
        
        enriched = infer_interfaces(tasks, model=MODEL_SONNET)
        
        assert len(enriched) == 2
        assert all(t.interface is not None for t in enriched)
        assert all(t.interface.input is not None for t in enriched)
        assert all(t.interface.output is not None for t in enriched)

