"""Result Aggregator - collects and merges parallel agent results.

Pulls artifacts from S3 after task completion and aggregates them
into a unified result. Detects conflicts when multiple agents
produce overlapping files.

Architecture (per Gemini guidance):
- S3 = Data channel (artifacts)
- SSM stdout = Control channel (status only)
- Aggregator pulls from S3, not SSM logs

Part of Blueprint Tier 3: Outpost Integration.
"""
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from blueprint.integrations.outpost import (
    OutpostDispatcher,
    DispatchResult,
    DispatchStatus,
    DEFAULT_BUCKET,
)


class AggregationStatus(str, Enum):
    """Overall aggregation status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL = "partial"  # Some tasks succeeded, some failed
    FAILED = "failed"
    CONFLICT = "conflict"  # File conflicts detected


@dataclass
class ArtifactInfo:
    """Information about a downloaded artifact."""
    task_id: str
    filename: str
    s3_key: str
    size_bytes: int
    last_modified: datetime
    local_path: Optional[Path] = None
    content_hash: Optional[str] = None


@dataclass
class ConflictInfo:
    """Information about a file conflict."""
    filename: str
    task_ids: list[str]
    resolution: Optional[str] = None  # Which task's version to use

@dataclass
class DownloadFailure:
    """Information about a failed artifact download."""
    task_id: str
    filename: str
    s3_key: str
    error: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AggregationResult:
    """Result of aggregating parallel task results."""
    run_id: str
    status: AggregationStatus
    task_results: list[DispatchResult]
    artifacts: list[ArtifactInfo]
    conflicts: list[ConflictInfo]
    download_failures: list[DownloadFailure] = field(default_factory=list)
    output_dir: Optional[Path] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    
    @property
    def success_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == DispatchStatus.SUCCESS)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == DispatchStatus.FAILED)
    
    @property
    def total_count(self) -> int:
        return len(self.task_results)
    
    def summary(self) -> str:
        return (
            f"Run {self.run_id}: {self.status.value} "
            f"({self.success_count}/{self.total_count} succeeded, "
            f"{len(self.artifacts)} artifacts, {len(self.conflicts)} conflicts)"
        )


class AggregationError(Exception):
    """Raised when aggregation fails."""
    pass


class ResultAggregator:
    """Aggregates results from parallel Outpost dispatches.
    
    Downloads artifacts from S3, detects conflicts, and merges
    results into a unified output directory.
    
    Example:
        >>> aggregator = ResultAggregator(dispatcher)
        >>> result = aggregator.aggregate(dispatch_results)
        >>> print(f"Downloaded {len(result.artifacts)} artifacts")
        >>> if result.conflicts:
        ...     print(f"Conflicts: {result.conflicts}")
    """
    
    def __init__(
        self,
        dispatcher: Optional[OutpostDispatcher] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        bucket: str = DEFAULT_BUCKET,
        region: str = "us-east-1",
    ):
        """Initialize the aggregator.
        
        Args:
            dispatcher: Existing dispatcher to share credentials.
            aws_access_key_id: AWS access key (if not using dispatcher).
            aws_secret_access_key: AWS secret key.
            bucket: S3 bucket for artifacts.
            region: AWS region.
        """
        self.bucket = bucket
        
        if dispatcher:
            self.s3 = dispatcher.s3
        else:
            session_kwargs = {"region_name": region}
            if aws_access_key_id and aws_secret_access_key:
                session_kwargs["aws_access_key_id"] = aws_access_key_id
                session_kwargs["aws_secret_access_key"] = aws_secret_access_key
            
            session = boto3.Session(**session_kwargs)
            self.s3 = session.client("s3")
    
    def aggregate(
        self,
        dispatch_results: list[DispatchResult],
        output_dir: Optional[Path] = None,
        resolve_conflicts: str = "latest",
    ) -> AggregationResult:
        """Aggregate results from parallel dispatches.
        
        Args:
            dispatch_results: Results from dispatcher.dispatch_parallel().
            output_dir: Directory to download artifacts to. Auto-created if None.
            resolve_conflicts: Conflict resolution strategy:
                - "latest": Use most recently modified file
                - "first": Use first task's version
                - "fail": Fail on conflicts
        
        Returns:
            AggregationResult with downloaded artifacts and any conflicts.
        """
        if not dispatch_results:
            raise AggregationError("No dispatch results to aggregate")
        
        run_id = dispatch_results[0].run_id
        
        # Create output directory
        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp(prefix=f"blueprint-{run_id}-"))
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        
        result = AggregationResult(
            run_id=run_id,
            status=AggregationStatus.PENDING,
            task_results=dispatch_results,
            artifacts=[],
            conflicts=[],
            output_dir=output_dir,
        )
        
        try:
            result.status = AggregationStatus.IN_PROGRESS
            
            # Collect artifacts from successful tasks
            all_artifacts = []
            for dispatch in dispatch_results:
                if dispatch.status == DispatchStatus.SUCCESS:
                    task_artifacts = self._list_task_artifacts(run_id, dispatch.task_id)
                    all_artifacts.extend(task_artifacts)
            
            # Detect conflicts (same filename from different tasks)
            conflicts = self._detect_conflicts(all_artifacts)
            result.conflicts = conflicts
            
            # Handle conflicts based on resolution strategy
            if conflicts and resolve_conflicts == "fail":
                result.status = AggregationStatus.CONFLICT
                result.error = f"File conflicts detected: {[c.filename for c in conflicts]}"
                result.completed_at = datetime.now(timezone.utc)
                return result
            
            # Download artifacts
            downloaded, dl_failures = self._download_artifacts(
                all_artifacts, output_dir, conflicts, resolve_conflicts
            )
            result.artifacts = downloaded
            result.download_failures = dl_failures
            
            # FAIL LOUD: If any downloads failed, update status and report
            if dl_failures:
                import sys
                print(
                    f"[AGGREGATOR] WARNING: {len(dl_failures)} artifact(s) failed to download",
                    file=sys.stderr
                )
                if result.status == AggregationStatus.SUCCESS:
                    result.status = AggregationStatus.PARTIAL
            
            # Determine final status
            if result.failed_count == result.total_count:
                result.status = AggregationStatus.FAILED
            elif result.failed_count > 0:
                result.status = AggregationStatus.PARTIAL
            elif conflicts:
                result.status = AggregationStatus.CONFLICT
            else:
                result.status = AggregationStatus.SUCCESS
            
            result.completed_at = datetime.now(timezone.utc)
            return result
            
        except Exception as e:
            result.status = AggregationStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now(timezone.utc)
            return result
    
    def wait_and_aggregate(
        self,
        dispatcher: OutpostDispatcher,
        dispatch_results: list[DispatchResult],
        output_dir: Optional[Path] = None,
        poll_interval: int = 10,
        max_wait: int = 3600,
    ) -> AggregationResult:
        """Wait for all dispatches to complete, then aggregate.
        
        Args:
            dispatcher: Dispatcher for polling.
            dispatch_results: Results from dispatch_parallel().
            output_dir: Output directory for artifacts.
            poll_interval: Seconds between polls.
            max_wait: Maximum wait time.
        
        Returns:
            AggregationResult after all tasks complete.
        """
        import time
        start = time.time()
        
        # Wait for all tasks to complete
        pending = list(dispatch_results)
        
        while pending and (time.time() - start) < max_wait:
            still_pending = []
            
            for result in pending:
                updated = dispatcher.poll(result.command_id)
                
                if updated.status in (
                    DispatchStatus.SUCCESS,
                    DispatchStatus.FAILED,
                    DispatchStatus.TIMEOUT,
                ):
                    # Update the original result
                    idx = dispatch_results.index(result)
                    dispatch_results[idx] = updated
                else:
                    still_pending.append(updated)
            
            pending = still_pending
            
            if pending:
                time.sleep(poll_interval)
        
        # Mark remaining as timeout
        for result in pending:
            result.status = DispatchStatus.TIMEOUT
            result.completed_at = datetime.now(timezone.utc)
        
        # Now aggregate
        return self.aggregate(dispatch_results, output_dir)
    
    def get_artifact_content(
        self,
        run_id: str,
        task_id: str,
        filename: str,
    ) -> bytes:
        """Get content of a specific artifact.
        
        Args:
            run_id: Run ID.
            task_id: Task ID.
            filename: Artifact filename.
        
        Returns:
            File content as bytes.
        """
        key = f"{run_id}/{task_id}/{filename}"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            raise AggregationError(f"Failed to get artifact {key}: {e}") from e
    
    def _list_task_artifacts(
        self,
        run_id: str,
        task_id: str,
    ) -> list[ArtifactInfo]:
        """List all artifacts for a task."""
        prefix = f"{run_id}/{task_id}/"
        artifacts = []
        
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    filename = key.replace(prefix, "")
                    
                    # Skip prompt file and empty filenames
                    if filename and filename != "task_prompt.md":
                        artifacts.append(ArtifactInfo(
                            task_id=task_id,
                            filename=filename,
                            s3_key=key,
                            size_bytes=obj["Size"],
                            last_modified=obj["LastModified"],
                        ))
            
            return artifacts
            
        except ClientError as e:
            raise AggregationError(f"Failed to list artifacts for {task_id}: {e}") from e
    
    def _detect_conflicts(
        self,
        artifacts: list[ArtifactInfo],
    ) -> list[ConflictInfo]:
        """Detect files produced by multiple tasks."""
        file_sources: dict[str, list[str]] = {}
        
        for artifact in artifacts:
            if artifact.filename not in file_sources:
                file_sources[artifact.filename] = []
            file_sources[artifact.filename].append(artifact.task_id)
        
        conflicts = []
        for filename, task_ids in file_sources.items():
            if len(task_ids) > 1:
                conflicts.append(ConflictInfo(
                    filename=filename,
                    task_ids=task_ids,
                ))
        
        return conflicts
    
    def _download_artifacts(
        self,
        artifacts: list[ArtifactInfo],
        output_dir: Path,
        conflicts: list[ConflictInfo],
        resolve_strategy: str,
    ) -> tuple[list[ArtifactInfo], list[DownloadFailure]]:
        """Download artifacts to output directory.
        
        Returns:
            Tuple of (downloaded artifacts, download failures).
            Failures are tracked explicitly per FAIL LOUD principle.
        """
        downloaded = []
        conflict_files = {c.filename for c in conflicts}
        
        # Group artifacts by filename
        by_filename: dict[str, list[ArtifactInfo]] = {}
        for artifact in artifacts:
            if artifact.filename not in by_filename:
                by_filename[artifact.filename] = []
            by_filename[artifact.filename].append(artifact)
        
        for filename, file_artifacts in by_filename.items():
            if filename in conflict_files:
                # Apply resolution strategy
                if resolve_strategy == "latest":
                    # Use most recently modified
                    winner = max(file_artifacts, key=lambda a: a.last_modified)
                elif resolve_strategy == "first":
                    # Use first task (alphabetically by task_id)
                    winner = min(file_artifacts, key=lambda a: a.task_id)
                else:
                    # Skip conflicted files
                    continue
                
                # Mark conflict resolution
                for conflict in conflicts:
                    if conflict.filename == filename:
                        conflict.resolution = winner.task_id
                
                artifact_to_download = winner
            else:
                artifact_to_download = file_artifacts[0]
            
            # Download the file
            local_path = output_dir / artifact_to_download.filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                self.s3.download_file(
                    self.bucket,
                    artifact_to_download.s3_key,
                    str(local_path),
                )
                artifact_to_download.local_path = local_path
                downloaded.append(artifact_to_download)
            except ClientError as e:
                # FAIL LOUD: Track download failures explicitly
                failure = DownloadFailure(
                    task_id=artifact_to_download.task_id,
                    filename=artifact_to_download.filename,
                    s3_key=artifact_to_download.s3_key,
                    error=str(e),
                )
                download_failures.append(failure)
                # Log to stderr for visibility
                import sys
                print(
                    f"[AGGREGATOR] Download failed: {artifact_to_download.filename} "
                    f"(task {artifact_to_download.task_id}): {e}",
                    file=sys.stderr
                )
        
        return downloaded, download_failures


def create_aggregator(
    dispatcher: Optional[OutpostDispatcher] = None,
    aws_access_key_id: Optional[str] = None,
    aws_secret_access_key: Optional[str] = None,
) -> ResultAggregator:
    """Create an aggregator with credentials.
    
    Args:
        dispatcher: Existing dispatcher to share credentials.
        aws_access_key_id: AWS access key.
        aws_secret_access_key: AWS secret key.
    
    Returns:
        Configured ResultAggregator.
    """
    return ResultAggregator(
        dispatcher=dispatcher,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )


# CLI support for testing
if __name__ == "__main__":
    print("Result Aggregator - use with OutpostDispatcher")
    print("Example:")
    print("  dispatcher = OutpostDispatcher(...)")
    print("  results = dispatcher.dispatch_parallel(tasks)")
    print("  aggregator = ResultAggregator(dispatcher)")
    print("  agg_result = aggregator.wait_and_aggregate(dispatcher, results)")
    print("  print(agg_result.summary())")

