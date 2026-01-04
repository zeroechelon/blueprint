"""Tests for structured logging with correlation IDs."""
import json
import logging
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO

from blueprint.logging import (
    LogLevel,
    LogEntry,
    StructuredLogger,
    CorrelationContext,
    get_logger,
    set_correlation_id,
    get_correlation_id,
    set_blueprint_id,
    get_blueprint_id,
    generate_correlation_id,
)


class TestLogEntry:
    """Tests for LogEntry dataclass."""
    
    def test_to_dict_removes_none_values(self):
        """LogEntry.to_dict() should exclude None fields."""
        entry = LogEntry(
            timestamp="2026-01-03T10:00:00Z",
            level=LogLevel.INFO,
            message="Test message",
            task_id="T1.1",
            # correlation_id, blueprint_id, etc. are None
        )
        result = entry.to_dict()
        
        assert "timestamp" in result
        assert "level" in result
        assert "message" in result
        assert "task_id" in result
        assert "correlation_id" not in result  # None excluded
        assert "blueprint_id" not in result    # None excluded
    
    def test_to_json_produces_valid_json(self):
        """LogEntry.to_json() should produce parseable JSON."""
        entry = LogEntry(
            timestamp="2026-01-03T10:00:00Z",
            level=LogLevel.ERROR,
            message="Something failed",
            correlation_id="corr_abc123",
            task_id="T2.1",
            duration_ms=42.5,
        )
        json_str = entry.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["level"] == "ERROR"
        assert parsed["message"] == "Something failed"
        assert parsed["correlation_id"] == "corr_abc123"
        assert parsed["duration_ms"] == 42.5
    
    def test_to_dict_includes_extra(self):
        """LogEntry should include extra dict when provided."""
        entry = LogEntry(
            timestamp="2026-01-03T10:00:00Z",
            level=LogLevel.DEBUG,
            message="Debug info",
            extra={"key": "value", "count": 42},
        )
        result = entry.to_dict()
        
        assert result["extra"] == {"key": "value", "count": 42}


class TestCorrelationContext:
    """Tests for CorrelationContext context manager."""
    
    def test_sets_and_restores_correlation_id(self):
        """Context manager should set ID on enter, restore on exit."""
        # Clear any existing state
        set_correlation_id(None)
        assert get_correlation_id() is None
        
        with CorrelationContext(correlation_id="test_corr_123") as cid:
            assert cid == "test_corr_123"
            assert get_correlation_id() == "test_corr_123"
        
        # After exit, should be restored to None
        assert get_correlation_id() is None
    
    def test_generates_correlation_id_if_not_provided(self):
        """Context manager should auto-generate ID if none provided."""
        set_correlation_id(None)
        
        with CorrelationContext() as cid:
            assert cid is not None
            assert cid.startswith("corr_")
            assert len(cid) == 21  # "corr_" + 16 hex chars
    
    def test_nested_contexts(self):
        """Nested contexts should properly save/restore."""
        set_correlation_id(None)
        
        with CorrelationContext(correlation_id="outer") as outer_cid:
            assert get_correlation_id() == "outer"
            
            with CorrelationContext(correlation_id="inner") as inner_cid:
                assert get_correlation_id() == "inner"
            
            # After inner exit, should restore to outer
            assert get_correlation_id() == "outer"
        
        # After outer exit, should restore to None
        assert get_correlation_id() is None
    
    def test_sets_blueprint_id(self):
        """Context manager should set blueprint_id when provided."""
        set_blueprint_id(None)
        
        with CorrelationContext(blueprint_id="bp_test_123"):
            assert get_blueprint_id() == "bp_test_123"
        
        assert get_blueprint_id() is None


class TestStructuredLogger:
    """Tests for StructuredLogger class."""
    
    def test_json_output_format(self):
        """Logger with json format should output valid JSON."""
        logger = StructuredLogger(name="test_json", output_format="json")
        
        # Capture log output
        with patch.object(logger._logger, 'log') as mock_log:
            set_correlation_id("test_corr")
            logger.info("Test message", task_id="T1.1")
            
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            log_message = call_args[0][1]  # Second positional arg is message
            
            # Should be valid JSON
            parsed = json.loads(log_message)
            assert parsed["message"] == "Test message"
            assert parsed["level"] == "INFO"
            assert parsed["task_id"] == "T1.1"
            assert parsed["correlation_id"] == "test_corr"
    
    def test_text_output_format(self):
        """Logger with text format should output readable text."""
        logger = StructuredLogger(name="test_text", output_format="text")
        
        with patch.object(logger._logger, 'log') as mock_log:
            set_correlation_id("corr_abc")
            set_blueprint_id("bp_xyz")
            logger.warning("Something happened", task_id="T2.1", duration_ms=100.5)
            
            mock_log.assert_called_once()
            log_message = mock_log.call_args[0][1]
            
            # Text format should contain key info
            assert "WARNING" in log_message
            assert "corr=corr_abc" in log_message
            assert "bp=bp_xyz" in log_message
            assert "task=T2.1" in log_message
            assert "dur=100.5ms" in log_message
            assert "Something happened" in log_message
    
    def test_all_log_levels(self):
        """All log level methods should work."""
        logger = StructuredLogger(name="test_levels", output_format="json")
        
        with patch.object(logger._logger, 'log') as mock_log:
            logger.debug("debug msg")
            logger.info("info msg")
            logger.warning("warning msg")
            logger.error("error msg")
            logger.critical("critical msg")
            
            assert mock_log.call_count == 5
            
            # Verify levels
            levels = [json.loads(call[0][1])["level"] for call in mock_log.call_args_list]
            assert levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class TestHelperFunctions:
    """Tests for module-level helper functions."""
    
    def test_generate_correlation_id_format(self):
        """generate_correlation_id should produce correct format."""
        cid = generate_correlation_id()
        
        assert cid.startswith("corr_")
        assert len(cid) == 21  # "corr_" (5) + 16 hex chars
        
        # Hex portion should be valid hex
        hex_part = cid[5:]
        int(hex_part, 16)  # Should not raise
    
    def test_generate_correlation_id_uniqueness(self):
        """Each call should generate unique ID."""
        ids = [generate_correlation_id() for _ in range(100)]
        assert len(set(ids)) == 100  # All unique
    
    def test_get_logger_returns_structured_logger(self):
        """get_logger should return StructuredLogger instance."""
        logger = get_logger()
        assert isinstance(logger, StructuredLogger)
        
        named_logger = get_logger("custom_name")
        assert isinstance(named_logger, StructuredLogger)
        assert named_logger.name == "custom_name"
    
    def test_correlation_id_setters_and_getters(self):
        """set/get correlation_id should work correctly."""
        set_correlation_id(None)
        assert get_correlation_id() is None
        
        set_correlation_id("my_corr_id")
        assert get_correlation_id() == "my_corr_id"
        
        set_correlation_id(None)
        assert get_correlation_id() is None
    
    def test_blueprint_id_setters_and_getters(self):
        """set/get blueprint_id should work correctly."""
        set_blueprint_id(None)
        assert get_blueprint_id() is None
        
        set_blueprint_id("my_bp_id")
        assert get_blueprint_id() == "my_bp_id"
        
        set_blueprint_id(None)
        assert get_blueprint_id() is None


class TestAsyncContextVars:
    """Tests verifying contextvars work correctly for async."""
    
    @pytest.mark.asyncio
    async def test_correlation_id_isolated_in_async_tasks(self):
        """Each async task should have isolated correlation context."""
        import asyncio
        
        results = {}
        
        async def task_with_context(name: str, cid: str):
            set_correlation_id(cid)
            await asyncio.sleep(0.01)  # Simulate async work
            results[name] = get_correlation_id()
        
        # Run tasks concurrently
        await asyncio.gather(
            task_with_context("task1", "corr_1"),
            task_with_context("task2", "corr_2"),
            task_with_context("task3", "corr_3"),
        )
        
        # Each task should have maintained its own correlation ID
        assert results["task1"] == "corr_1"
        assert results["task2"] == "corr_2"
        assert results["task3"] == "corr_3"
