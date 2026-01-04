"""Tests for the Outpost dispatcher.

These tests verify the dispatcher can send commands to SSM and
manage artifacts via S3.
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from blueprint.integrations.outpost import (
    OutpostDispatcher,
    DispatchResult,
    DispatchStatus,
    DispatchError,
    create_dispatcher,
    DEFAULT_BUCKET,
    DEFAULT_SSM_INSTANCE,
)


class TestOutpostDispatcher:
    """Test suite for OutpostDispatcher class."""
    
    @pytest.fixture
    def mock_boto_session(self):
        """Create mock boto3 session."""
        with patch("blueprint.integrations.outpost.boto3.Session") as mock:
            session = Mock()
            mock.return_value = session
            
            # Mock SSM client
            ssm = Mock()
            # Mock S3 client
            s3 = Mock()
            s3.list_objects_v2.return_value = {"Contents": []}
            
            def get_client(name):
                if name == "ssm":
                    return ssm
                elif name == "s3":
                    return s3
                return Mock()
            
            session.client.side_effect = get_client
            
            yield mock, session, ssm, s3
    
    @pytest.fixture
    def sample_task(self):
        """Sample task for testing."""
        return {
            "task_id": "T1",
            "name": "Test task",
            "description": "A test task",
            "interface": {"input": "None", "output": "Result"},
            "acceptance_criteria": ["Task completed"],
            "files_to_create": ["test.py"],
        }
    
    def test_init_creates_boto_session(self, mock_boto_session):
        """Should create boto3 session with provided credentials."""
        mock, session, ssm, s3 = mock_boto_session
        
        dispatcher = OutpostDispatcher(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )
        
        mock.assert_called_once()
        call_kwargs = mock.call_args[1]
        assert call_kwargs["aws_access_key_id"] == "test-key"
        assert call_kwargs["aws_secret_access_key"] == "test-secret"
    
    def test_init_uses_default_bucket_and_instance(self, mock_boto_session):
        """Should use default bucket and SSM instance."""
        mock, session, ssm, s3 = mock_boto_session
        
        dispatcher = OutpostDispatcher()
        
        assert dispatcher.bucket == DEFAULT_BUCKET
        assert dispatcher.ssm_instance == DEFAULT_SSM_INSTANCE
    
    def test_generate_run_id_format(self, mock_boto_session):
        """Should generate run ID in expected format."""
        mock, session, ssm, s3 = mock_boto_session
        dispatcher = OutpostDispatcher()
        
        run_id = dispatcher._generate_run_id()
        
        assert run_id.startswith("run-")
        assert len(run_id) > 20  # Has timestamp and UUID
    
    def test_dispatch_sends_ssm_command(self, mock_boto_session, sample_task):
        """Should send SSM command with task details."""
        mock, session, ssm, s3 = mock_boto_session
        
        ssm.send_command.return_value = {
            "Command": {"CommandId": "cmd-123"}
        }
        
        dispatcher = OutpostDispatcher()
        result = dispatcher.dispatch(sample_task, agent="claude")
        
        ssm.send_command.assert_called_once()
        call_kwargs = ssm.send_command.call_args[1]
        
        assert dispatcher.ssm_instance in call_kwargs["InstanceIds"]
        assert call_kwargs["DocumentName"] == "AWS-RunShellScript"
        assert "T1" in call_kwargs["Comment"]
    
    def test_dispatch_returns_result_with_command_id(self, mock_boto_session, sample_task):
        """Should return DispatchResult with command ID."""
        mock, session, ssm, s3 = mock_boto_session
        
        ssm.send_command.return_value = {
            "Command": {"CommandId": "cmd-456"}
        }
        
        dispatcher = OutpostDispatcher()
        result = dispatcher.dispatch(sample_task, agent="claude")
        
        assert result.command_id == "cmd-456"
        assert result.task_id == "T1"
        assert result.agent == "claude"
        assert result.status == DispatchStatus.PENDING
    
    def test_dispatch_raises_on_invalid_agent(self, mock_boto_session, sample_task):
        """Should raise error for unknown agent."""
        mock, session, ssm, s3 = mock_boto_session
        dispatcher = OutpostDispatcher()
        
        with pytest.raises(DispatchError, match="Unknown agent"):
            dispatcher.dispatch(sample_task, agent="unknown_agent")
    
    def test_dispatch_uses_shared_run_id(self, mock_boto_session, sample_task):
        """Should use provided run_id for multiple dispatches."""
        mock, session, ssm, s3 = mock_boto_session
        
        ssm.send_command.return_value = {
            "Command": {"CommandId": "cmd-789"}
        }
        
        dispatcher = OutpostDispatcher()
        result = dispatcher.dispatch(sample_task, agent="claude", run_id="shared-run")
        
        assert result.run_id == "shared-run"
        assert "shared-run" in result.s3_path
    
    def test_poll_updates_status(self, mock_boto_session, sample_task):
        """Should update result status from SSM."""
        mock, session, ssm, s3 = mock_boto_session
        
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-poll"}}
        ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "TASK_COMPLETE: T1",
        }
        
        dispatcher = OutpostDispatcher()
        dispatch_result = dispatcher.dispatch(sample_task, agent="claude")
        
        result = dispatcher.poll(dispatch_result.command_id)
        
        assert result.status == DispatchStatus.SUCCESS
        assert result.exit_code == 0
        assert result.completed_at is not None
    
    def test_poll_captures_error(self, mock_boto_session, sample_task):
        """Should capture stderr on failure."""
        mock, session, ssm, s3 = mock_boto_session
        
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-fail"}}
        ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "ResponseCode": 1,
            "StandardErrorContent": "Error: something went wrong",
        }
        
        dispatcher = OutpostDispatcher()
        dispatch_result = dispatcher.dispatch(sample_task, agent="claude")
        
        result = dispatcher.poll(dispatch_result.command_id)
        
        assert result.status == DispatchStatus.FAILED
        assert "something went wrong" in result.error
    
    def test_poll_raises_on_unknown_command(self, mock_boto_session):
        """Should raise error for unknown command ID."""
        mock, session, ssm, s3 = mock_boto_session
        dispatcher = OutpostDispatcher()
        
        with pytest.raises(DispatchError, match="Unknown command_id"):
            dispatcher.poll("nonexistent-cmd")
    
    def test_dispatch_parallel_uses_same_run_id(self, mock_boto_session, sample_task):
        """Should use same run_id for all parallel dispatches."""
        mock, session, ssm, s3 = mock_boto_session
        
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-parallel"}}
        
        tasks = [
            {**sample_task, "task_id": "T1"},
            {**sample_task, "task_id": "T2"},
            {**sample_task, "task_id": "T3"},
        ]
        
        dispatcher = OutpostDispatcher()
        results = dispatcher.dispatch_parallel(tasks, agent="claude")
        
        assert len(results) == 3
        assert all(r.run_id == results[0].run_id for r in results)
    
    def test_build_task_prompt_includes_required_fields(self, mock_boto_session, sample_task):
        """Should include all required fields in task prompt."""
        mock, session, ssm, s3 = mock_boto_session
        dispatcher = OutpostDispatcher()
        
        prompt = dispatcher._build_task_prompt(sample_task, "s3://bucket/path/")
        
        assert "T1" in prompt
        assert "Test task" in prompt
        assert "Task completed" in prompt
        assert "test.py" in prompt
        assert "s3://bucket/path/" in prompt
        assert "TASK_COMPLETE" in prompt
    
    def test_build_ssm_command_includes_s3_sync(self, mock_boto_session, sample_task):
        """Should include S3 sync in SSM command."""
        mock, session, ssm, s3 = mock_boto_session
        dispatcher = OutpostDispatcher()
        
        command = dispatcher._build_ssm_command(
            "T1",
            "Test prompt",
            "s3://bucket/run/T1/",
            "dispatch.sh",
        )
        
        assert "aws s3 sync" in command
        assert "s3://bucket/run/T1/" in command
        assert "dispatch.sh" in command


class TestCreateDispatcher:
    """Test suite for create_dispatcher function."""
    
    def test_creates_dispatcher(self):
        """Should create configured dispatcher."""
        with patch("blueprint.integrations.outpost.boto3.Session"):
            dispatcher = create_dispatcher(
                aws_access_key_id="key",
                aws_secret_access_key="secret",
            )
            
            assert isinstance(dispatcher, OutpostDispatcher)


# Integration test - requires actual AWS credentials
@pytest.mark.skipif(
    not os.environ.get("AWS_ACCESS_KEY_ID"),
    reason="AWS credentials not set"
)
class TestDispatcherIntegration:
    """Integration tests that require actual AWS access."""
    
    def test_real_dispatch(self):
        """Test actual dispatch (will fail without Outpost setup)."""
        # This test is intentionally minimal - full integration
        # requires the Outpost agent fleet to be running
        dispatcher = OutpostDispatcher()
        
        # Just verify we can create a dispatcher with env credentials
        assert dispatcher.ssm is not None
        assert dispatcher.s3 is not None
