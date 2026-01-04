"""Tests for the Result Aggregator.

These tests verify the aggregator can pull artifacts from S3,
detect conflicts, and merge results correctly.
"""
import os
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from blueprint.integrations.aggregator import (
    ResultAggregator,
    AggregationResult,
    AggregationStatus,
    AggregationError,
    ArtifactInfo,
    ConflictInfo,
    create_aggregator,
)
from blueprint.integrations.outpost import (
    DispatchResult,
    DispatchStatus,
)


class TestResultAggregator:
    """Test suite for ResultAggregator class."""
    
    @pytest.fixture
    def mock_s3(self):
        """Create mock S3 client."""
        with patch("blueprint.integrations.aggregator.boto3.Session") as mock:
            session = Mock()
            mock.return_value = session
            
            s3 = Mock()
            session.client.return_value = s3
            
            yield s3
    
    @pytest.fixture
    def sample_dispatch_results(self):
        """Sample dispatch results for testing."""
        return [
            DispatchResult(
                task_id="T1",
                command_id="cmd-1",
                run_id="run-test",
                agent="claude",
                status=DispatchStatus.SUCCESS,
                s3_path="s3://bucket/run-test/T1/",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ),
            DispatchResult(
                task_id="T2",
                command_id="cmd-2",
                run_id="run-test",
                agent="claude",
                status=DispatchStatus.SUCCESS,
                s3_path="s3://bucket/run-test/T2/",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ),
        ]
    
    def test_init_creates_s3_client(self, mock_s3):
        """Should create S3 client with credentials."""
        aggregator = ResultAggregator(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )
        
        assert aggregator.s3 is not None
    
    def test_init_uses_dispatcher_s3(self):
        """Should use S3 client from dispatcher if provided."""
        mock_dispatcher = Mock()
        mock_dispatcher.s3 = Mock()
        
        aggregator = ResultAggregator(dispatcher=mock_dispatcher)
        
        assert aggregator.s3 == mock_dispatcher.s3
    
    def test_detect_conflicts_finds_overlapping_files(self, mock_s3):
        """Should detect when multiple tasks produce same file."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        
        artifacts = [
            ArtifactInfo(
                task_id="T1",
                filename="config.py",
                s3_key="run/T1/config.py",
                size_bytes=100,
                last_modified=datetime.now(timezone.utc),
            ),
            ArtifactInfo(
                task_id="T2",
                filename="config.py",  # Same filename!
                s3_key="run/T2/config.py",
                size_bytes=150,
                last_modified=datetime.now(timezone.utc),
            ),
            ArtifactInfo(
                task_id="T1",
                filename="main.py",
                s3_key="run/T1/main.py",
                size_bytes=200,
                last_modified=datetime.now(timezone.utc),
            ),
        ]
        
        conflicts = aggregator._detect_conflicts(artifacts)
        
        assert len(conflicts) == 1
        assert conflicts[0].filename == "config.py"
        assert set(conflicts[0].task_ids) == {"T1", "T2"}
    
    def test_detect_conflicts_returns_empty_for_unique_files(self, mock_s3):
        """Should return empty list when no conflicts."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        
        artifacts = [
            ArtifactInfo(
                task_id="T1",
                filename="file1.py",
                s3_key="run/T1/file1.py",
                size_bytes=100,
                last_modified=datetime.now(timezone.utc),
            ),
            ArtifactInfo(
                task_id="T2",
                filename="file2.py",
                s3_key="run/T2/file2.py",
                size_bytes=150,
                last_modified=datetime.now(timezone.utc),
            ),
        ]
        
        conflicts = aggregator._detect_conflicts(artifacts)
        
        assert len(conflicts) == 0
    
    def test_aggregate_raises_on_empty_results(self, mock_s3):
        """Should raise error if no results provided."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        
        with pytest.raises(AggregationError, match="No dispatch results"):
            aggregator.aggregate([])
    
    def test_aggregate_returns_result_with_run_id(self, mock_s3, sample_dispatch_results):
        """Should return result with correct run_id."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        
        # Mock S3 list to return no artifacts
        mock_s3.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
        
        result = aggregator.aggregate(sample_dispatch_results)
        
        assert result.run_id == "run-test"
    
    def test_aggregate_counts_success_and_failure(self, mock_s3):
        """Should correctly count successful and failed tasks."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        
        results = [
            DispatchResult(
                task_id="T1", command_id="1", run_id="run",
                agent="claude", status=DispatchStatus.SUCCESS,
                s3_path="s3://b/run/T1/",
                started_at=datetime.now(timezone.utc),
            ),
            DispatchResult(
                task_id="T2", command_id="2", run_id="run",
                agent="claude", status=DispatchStatus.FAILED,
                s3_path="s3://b/run/T2/",
                started_at=datetime.now(timezone.utc),
            ),
        ]
        
        mock_s3.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
        
        result = aggregator.aggregate(results)
        
        assert result.success_count == 1
        assert result.failed_count == 1
        assert result.total_count == 2
        assert result.status == AggregationStatus.PARTIAL
    
    def test_aggregate_sets_conflict_status(self, mock_s3, sample_dispatch_results):
        """Should set CONFLICT status when conflicts detected with fail strategy."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        aggregator.s3 = mock_s3  # Use the mock directly
        
        # Mock S3 paginator to return conflicting files
        paginator = Mock()
        def mock_paginate(Bucket, Prefix):
            if "T1" in Prefix:
                return [{"Contents": [
                    {"Key": f"{Prefix}shared.py", "Size": 100, "LastModified": datetime.now(timezone.utc)}
                ]}]
            elif "T2" in Prefix:
                return [{"Contents": [
                    {"Key": f"{Prefix}shared.py", "Size": 150, "LastModified": datetime.now(timezone.utc)}
                ]}]
            return [{"Contents": []}]
        
        paginator.paginate = mock_paginate
        mock_s3.get_paginator.return_value = paginator
        
        result = aggregator.aggregate(sample_dispatch_results, resolve_conflicts="fail")
        
        assert result.status == AggregationStatus.CONFLICT
        assert len(result.conflicts) == 1
    
    def test_aggregate_resolves_conflicts_with_latest(self, mock_s3, sample_dispatch_results):
        """Should resolve conflicts using latest modified file."""
        aggregator = ResultAggregator(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        aggregator.s3 = mock_s3  # Use the mock directly
        
        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new_time = datetime(2024, 1, 2, tzinfo=timezone.utc)
        
        # Mock paginator
        paginator = Mock()
        def mock_paginate(Bucket, Prefix):
            if "T1" in Prefix:
                return [{"Contents": [
                    {"Key": f"{Prefix}shared.py", "Size": 100, "LastModified": old_time}
                ]}]
            elif "T2" in Prefix:
                return [{"Contents": [
                    {"Key": f"{Prefix}shared.py", "Size": 150, "LastModified": new_time}
                ]}]
            return [{"Contents": []}]
        
        paginator.paginate = mock_paginate
        mock_s3.get_paginator.return_value = paginator
        mock_s3.download_file = Mock()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            result = aggregator.aggregate(
                sample_dispatch_results,
                output_dir=Path(tmpdir),
                resolve_conflicts="latest",
            )
            
            # Should have resolved conflict using T2 (newer)
            assert len(result.conflicts) == 1
            assert result.conflicts[0].resolution == "T2"
    
    def test_aggregation_result_summary(self):
        """Should produce readable summary."""
        result = AggregationResult(
            run_id="run-123",
            status=AggregationStatus.SUCCESS,
            task_results=[],
            artifacts=[],
            conflicts=[],
        )
        
        summary = result.summary()
        
        assert "run-123" in summary
        assert "success" in summary.lower()


class TestCreateAggregator:
    """Test suite for create_aggregator function."""
    
    def test_creates_with_dispatcher(self):
        """Should create aggregator using dispatcher's S3 client."""
        mock_dispatcher = Mock()
        mock_dispatcher.s3 = Mock()
        
        aggregator = create_aggregator(dispatcher=mock_dispatcher)
        
        assert isinstance(aggregator, ResultAggregator)
        assert aggregator.s3 == mock_dispatcher.s3
    
    def test_creates_with_credentials(self):
        """Should create aggregator with AWS credentials."""
        with patch("blueprint.integrations.aggregator.boto3.Session"):
            aggregator = create_aggregator(
                aws_access_key_id="key",
                aws_secret_access_key="secret",
            )
            
            assert isinstance(aggregator, ResultAggregator)
