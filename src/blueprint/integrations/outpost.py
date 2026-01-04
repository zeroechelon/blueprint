"""Outpost Dispatcher - async multi-agent task dispatch via SSM.

Dispatches Blueprint tasks to the Outpost agent fleet (Claude Code, Codex, Gemini)
using AWS Systems Manager for command execution.

Architecture (per Gemini guidance):
- SSM = Control channel (status, logs, ~48KB limit)  
- S3 = Data channel (artifacts, unlimited)

Agents write artifacts to S3, not stdout. This avoids SSM truncation.

Protocol:
1. Dispatcher generates run_id and task workspace
2. Agent receives task spec + S3 output path
3. Agent writes artifacts to local temp, then syncs to S3
4. Agent signals completion via stdout (status only)
5. Aggregator pulls artifacts from S3

Part of Blueprint Tier 3: Outpost Integration.
"""
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import boto3
from botocore.exceptions import ClientError


# Configuration
DEFAULT_REGION = "us-east-1"
DEFAULT_BUCKET = None  # Configure via BLUEPRINT_S3_BUCKET env var
DEFAULT_SSM_INSTANCE = None  # Configure via BLUEPRINT_SSM_INSTANCE env var
EXECUTOR_PATH = "/opt/blueprint/executor"  # Override via BLUEPRINT_EXECUTOR_PATH

# Agent dispatch scripts (from Outpost project)
AGENT_DISPATCH_SCRIPTS = {
    "claude": "dispatch.sh",
    "codex": "dispatch-codex.sh",
    "gemini": "dispatch-gemini.sh",
}


class DispatchStatus(str, Enum):
    """Task dispatch status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class DispatchResult:
    """Result of a task dispatch."""
    task_id: str
    command_id: str
    run_id: str
    agent: str
    status: DispatchStatus
    s3_path: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    stdout_snippet: Optional[str] = None  # Just status, not full output
    error: Optional[str] = None
    artifacts: list[str] = field(default_factory=list)


class DispatchError(Exception):
    """Raised when dispatch fails."""
    pass


class OutpostDispatcher:
    """Dispatches tasks to Outpost agent fleet.
    
    Uses SSM Run Command for async execution and S3 for artifact storage.
    
    Example:
        >>> dispatcher = OutpostDispatcher()
        >>> result = dispatcher.dispatch(task, agent="claude")
        >>> print(result.command_id)
        "abc123..."
        >>> 
        >>> # Later, poll for completion
        >>> result = dispatcher.poll(result.command_id)
        >>> if result.status == DispatchStatus.SUCCESS:
        ...     print(f"Artifacts: {result.artifacts}")
    """
    
    def __init__(
        self,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region: str = DEFAULT_REGION,
        bucket: str = DEFAULT_BUCKET,
        ssm_instance: str = DEFAULT_SSM_INSTANCE,
    ):
        """Initialize the dispatcher.
        
        Args:
            aws_access_key_id: AWS access key (or use env/role).
            aws_secret_access_key: AWS secret key.
            region: AWS region.
            bucket: S3 bucket for artifacts.
            ssm_instance: SSM instance ID for agent host.
        """
        self.region = region
        self.bucket = bucket
        self.ssm_instance = ssm_instance
        
        # Create boto3 session
        session_kwargs = {"region_name": region}
        if aws_access_key_id and aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
        
        self.session = boto3.Session(**session_kwargs)
        self.ssm = self.session.client("ssm")
        self.s3 = self.session.client("s3")
        
        # Track dispatched tasks
        self._dispatches: dict[str, DispatchResult] = {}
    
    def dispatch(
        self,
        task: dict,
        agent: str = "claude",
        run_id: Optional[str] = None,
        timeout_seconds: int = 3600,
    ) -> DispatchResult:
        """Dispatch a task to an agent.
        
        Args:
            task: Task dictionary with task_id, name, interface, etc.
            agent: Agent to use ("claude", "codex", "gemini").
            run_id: Run ID for grouping tasks. Auto-generated if not provided.
            timeout_seconds: Max execution time.
        
        Returns:
            DispatchResult with command_id for polling.
        
        Raises:
            DispatchError: If dispatch fails.
        """
        task_id = task.get("task_id", "unknown")
        run_id = run_id or self._generate_run_id()
        
        # Validate agent
        if agent not in AGENT_DISPATCH_SCRIPTS:
            raise DispatchError(f"Unknown agent: {agent}. Valid: {list(AGENT_DISPATCH_SCRIPTS.keys())}")
        
        # Build S3 paths
        s3_prefix = f"{run_id}/{task_id}"
        s3_path = f"s3://{self.bucket}/{s3_prefix}/"
        
        # Build task prompt
        task_prompt = self._build_task_prompt(task, s3_path)
        
        # Build SSM command
        dispatch_script = AGENT_DISPATCH_SCRIPTS[agent]
        command = self._build_ssm_command(task_id, task_prompt, s3_path, dispatch_script)
        
        try:
            # Send SSM command
            response = self.ssm.send_command(
                InstanceIds=[self.ssm_instance],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [command]},
                TimeoutSeconds=timeout_seconds,
                Comment=f"Blueprint task: {task_id} ({task.get('name', 'N/A')})",
            )
            
            command_id = response["Command"]["CommandId"]
            
            result = DispatchResult(
                task_id=task_id,
                command_id=command_id,
                run_id=run_id,
                agent=agent,
                status=DispatchStatus.PENDING,
                s3_path=s3_path,
                started_at=datetime.now(timezone.utc),
            )
            
            self._dispatches[command_id] = result
            return result
            
        except ClientError as e:
            raise DispatchError(f"SSM dispatch failed: {e}") from e
    
    def poll(self, command_id: str) -> DispatchResult:
        """Poll for task completion.
        
        Args:
            command_id: Command ID from dispatch.
        
        Returns:
            Updated DispatchResult.
        """
        if command_id not in self._dispatches:
            raise DispatchError(f"Unknown command_id: {command_id}")
        
        result = self._dispatches[command_id]
        
        try:
            response = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=self.ssm_instance,
            )
            
            status_map = {
                "Pending": DispatchStatus.PENDING,
                "InProgress": DispatchStatus.IN_PROGRESS,
                "Success": DispatchStatus.SUCCESS,
                "Failed": DispatchStatus.FAILED,
                "TimedOut": DispatchStatus.TIMEOUT,
                "Cancelled": DispatchStatus.FAILED,
            }
            
            ssm_status = response.get("Status", "Pending")
            result.status = status_map.get(ssm_status, DispatchStatus.PENDING)
            
            if result.status in (DispatchStatus.SUCCESS, DispatchStatus.FAILED, DispatchStatus.TIMEOUT):
                result.completed_at = datetime.now(timezone.utc)
                result.exit_code = response.get("ResponseCode")
                
                # Get stdout snippet (status only, not full output)
                stdout = response.get("StandardOutputContent", "")
                result.stdout_snippet = stdout[:1000] if stdout else None
                
                stderr = response.get("StandardErrorContent", "")
                if stderr:
                    result.error = stderr[:1000]
                
                # List artifacts from S3
                if result.status == DispatchStatus.SUCCESS:
                    result.artifacts = self._list_artifacts(result.run_id, result.task_id)
            
            return result
            
        except ClientError as e:
            if "InvocationDoesNotExist" in str(e):
                # Command still pending
                return result
            raise DispatchError(f"Poll failed: {e}") from e
    
    def wait_for_completion(
        self,
        command_id: str,
        poll_interval: int = 10,
        max_wait: int = 3600,
    ) -> DispatchResult:
        """Wait for task completion (blocking).
        
        Args:
            command_id: Command ID from dispatch.
            poll_interval: Seconds between polls.
            max_wait: Maximum wait time.
        
        Returns:
            Final DispatchResult.
        """
        start = time.time()
        
        while time.time() - start < max_wait:
            result = self.poll(command_id)
            
            if result.status in (DispatchStatus.SUCCESS, DispatchStatus.FAILED, DispatchStatus.TIMEOUT):
                return result
            
            time.sleep(poll_interval)
        
        result = self._dispatches.get(command_id)
        if result:
            result.status = DispatchStatus.TIMEOUT
            result.completed_at = datetime.now(timezone.utc)
        return result
    
    def dispatch_parallel(
        self,
        tasks: list[dict],
        agent: str = "claude",
        run_id: Optional[str] = None,
    ) -> list[DispatchResult]:
        """Dispatch multiple tasks in parallel.
        
        Args:
            tasks: List of task dictionaries.
            agent: Agent to use for all tasks.
            run_id: Shared run ID.
        
        Returns:
            List of DispatchResults.
        """
        run_id = run_id or self._generate_run_id()
        results = []
        
        for task in tasks:
            result = self.dispatch(task, agent=agent, run_id=run_id)
            results.append(result)
        
        return results
    
    def get_artifact(self, run_id: str, task_id: str, filename: str) -> bytes:
        """Download a specific artifact from S3.
        
        Args:
            run_id: Run ID.
            task_id: Task ID.
            filename: Artifact filename.
        
        Returns:
            File contents as bytes.
        """
        key = f"{run_id}/{task_id}/{filename}"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            raise DispatchError(f"Failed to get artifact {key}: {e}") from e
    
    def _generate_run_id(self) -> str:
        """Generate a unique run ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        return f"run-{timestamp}-{short_uuid}"
    
    def _build_task_prompt(self, task: dict, s3_path: str) -> str:
        """Build the prompt to send to the agent."""
        interface = task.get("interface", {})
        criteria = task.get("acceptance_criteria", [])
        files_to_create = task.get("files_to_create", [])
        
        criteria_str = "\n".join(f"- {c}" for c in criteria)
        files_str = "\n".join(f"- {f}" for f in files_to_create) if files_to_create else "- As needed"
        
        return f"""## Task: {task.get('name', task.get('task_id', 'Unknown'))}

**Task ID**: {task.get('task_id', 'N/A')}

### Description
{task.get('description', 'Complete this task.')}

### Interface
- **Input**: {interface.get('input', 'See task description')}
- **Output**: {interface.get('output', 'Task completion')}

### Acceptance Criteria
{criteria_str}

### Files to Create
{files_str}

### Output Instructions (CRITICAL)
You MUST write all generated files to the local workspace.
After completion, the system will sync your files to: {s3_path}

DO NOT print large code blocks to stdout. Write them to files instead.
Print only status messages and brief summaries to stdout.

When complete, print: "TASK_COMPLETE: {task.get('task_id', 'N/A')}"
If you encounter an error, print: "TASK_FAILED: {task.get('task_id', 'N/A')}: <error message>"
"""

    def _build_ssm_command(
        self,
        task_id: str,
        task_prompt: str,
        s3_path: str,
        dispatch_script: str,
    ) -> str:
        """Build the SSM shell command.
        
        Outpost dispatch scripts expect: ./dispatch.sh <workspace> "<prompt>"
        They run the agent and output goes to the workspace.
        """
        # Escape the prompt for shell (double-escape for nested quotes)
        escaped_prompt = task_prompt.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        
        # Build command that:
        # 1. Creates workspace
        # 2. Runs agent with prompt
        # 3. Syncs artifacts to S3
        return f"""#!/bin/bash
set -e

# Configuration
WORKSPACE="/tmp/blueprint/{task_id}"
S3_PATH="{s3_path}"
EXECUTOR="{EXECUTOR_PATH}"

# Setup workspace
rm -rf "$WORKSPACE" 2>/dev/null || true
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

# Write task prompt to file for reference
cat > task_prompt.md << 'PROMPT_EOF'
{task_prompt}
PROMPT_EOF

# Run agent
echo "Starting agent for task {task_id}..."
cd "$EXECUTOR"

# Execute dispatch script with workspace and prompt
# The dispatch scripts output to the workspace directory
if [ -f "{dispatch_script}" ]; then
    ./{dispatch_script} "$WORKSPACE" "{escaped_prompt}" 2>&1 || echo "Agent exited with code $?"
else
    echo "TASK_FAILED: {task_id}: Dispatch script not found: {dispatch_script}"
    exit 1
fi

# Sync artifacts to S3 (excluding prompt file)
echo ""
echo "Syncing artifacts to S3..."
cd "$WORKSPACE"
aws s3 sync . "$S3_PATH" --exclude "task_prompt.md" --quiet 2>/dev/null || echo "S3 sync skipped"

# List generated files
echo ""
echo "Generated files:"
ls -la "$WORKSPACE" 2>/dev/null || echo "No files"

# Report completion
echo ""
echo "Artifacts synced to: $S3_PATH"
echo "TASK_COMPLETE: {task_id}"
"""

    def _list_artifacts(self, run_id: str, task_id: str) -> list[str]:
        """List artifacts in S3 for a task."""
        prefix = f"{run_id}/{task_id}/"
        
        try:
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
            )
            
            artifacts = []
            for obj in response.get("Contents", []):
                key = obj["Key"]
                filename = key.replace(prefix, "")
                if filename and filename != "task_prompt.md":
                    artifacts.append(filename)
            
            return artifacts
            
        except ClientError:
            return []


def create_dispatcher(
    aws_access_key_id: Optional[str] = None,
    aws_secret_access_key: Optional[str] = None,
) -> OutpostDispatcher:
    """Create a dispatcher with default or provided credentials.
    
    Args:
        aws_access_key_id: AWS access key.
        aws_secret_access_key: AWS secret key.
    
    Returns:
        Configured OutpostDispatcher.
    """
    return OutpostDispatcher(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

