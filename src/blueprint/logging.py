"""Structured logging with correlation IDs for Blueprint execution.

Provides observability for async execution by tracking:
- Blueprint execution runs
- Individual task execution
- Parallel group execution
- Dependency resolution
"""
import logging
import uuid
import json
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum


class LogLevel(str, Enum):
    """Log levels for structured logging."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """A structured log entry."""
    timestamp: str
    level: LogLevel
    message: str
    correlation_id: Optional[str] = None
    blueprint_id: Optional[str] = None
    task_id: Optional[str] = None
    tier_id: Optional[str] = None
    group_id: Optional[str] = None
    component: Optional[str] = None
    duration_ms: Optional[float] = None
    extra: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Remove None values for cleaner output
        return {k: v for k, v in result.items() if v is not None}
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# Context variables for correlation tracking
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_blueprint_id: ContextVar[Optional[str]] = ContextVar("blueprint_id", default=None)


class StructuredLogger:
    """Structured logger with correlation ID support."""
    
    def __init__(
        self,
        name: str = "blueprint",
        level: LogLevel = LogLevel.INFO,
        output_format: str = "json",  # "json" or "text"
    ):
        self.name = name
        self.level = level
        self.output_format = output_format
        self._logger = logging.getLogger(name)
        
        # Configure handler if none exists
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = self._get_formatter()
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.DEBUG)
            self._logger.propagate = False
    
    def _get_formatter(self):
        """Get appropriate formatter based on output format."""
        if self.output_format == "json":
            return logging.Formatter('%(message)s')
        else:
            return logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    def _log(
        self,
        level: LogLevel,
        message: str,
        task_id: Optional[str] = None,
        tier_id: Optional[str] = None,
        group_id: Optional[str] = None,
        component: Optional[str] = None,
        duration_ms: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """Internal logging method."""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level,
            message=message,
            correlation_id=_correlation_id.get(),
            blueprint_id=_blueprint_id.get(),
            task_id=task_id,
            tier_id=tier_id,
            group_id=group_id,
            component=component,
            duration_ms=duration_ms,
            extra=extra,
        )
        
        if self.output_format == "json":
            log_message = entry.to_json()
        else:
            # Text format for readability
            parts = [
                f"[{entry.timestamp}]",
                f"{level.value}",
                f"corr={entry.correlation_id or 'N/A'}",
                f"bp={entry.blueprint_id or 'N/A'}",
            ]
            if task_id:
                parts.append(f"task={task_id}")
            if tier_id:
                parts.append(f"tier={tier_id}")
            if group_id:
                parts.append(f"group={group_id}")
            if component:
                parts.append(f"comp={component}")
            if duration_ms is not None:
                parts.append(f"dur={duration_ms:.1f}ms")
            parts.append(message)
            log_message = " ".join(parts)
        
        # Map to Python logging levels
        level_map = {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL,
        }
        
        self._logger.log(level_map[level], log_message)
    
    def debug(self, message: str, **kwargs):
        self._log(LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self._log(LogLevel.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log(LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log(LogLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log(LogLevel.CRITICAL, message, **kwargs)


# Global logger instance
_logger = StructuredLogger()


def get_logger(name: Optional[str] = None) -> StructuredLogger:
    """Get a structured logger instance."""
    if name:
        return StructuredLogger(name=name)
    return _logger


def set_correlation_id(cid: Optional[str]) -> None:
    """Set the current correlation ID."""
    if cid:
        _correlation_id.set(cid)
    else:
        _correlation_id.set(None)


def set_blueprint_id(bid: Optional[str]) -> None:
    """Set the current blueprint ID."""
    if bid:
        _blueprint_id.set(bid)
    else:
        _blueprint_id.set(None)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID."""
    return _correlation_id.get()


def get_blueprint_id() -> Optional[str]:
    """Get the current blueprint ID."""
    return _blueprint_id.get()


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return f"corr_{uuid.uuid4().hex[:16]}"


class CorrelationContext:
    """Context manager for correlation ID scoping."""
    
    def __init__(
        self,
        correlation_id: Optional[str] = None,
        blueprint_id: Optional[str] = None,
    ):
        self.correlation_id = correlation_id or generate_correlation_id()
        self.blueprint_id = blueprint_id
        self._prev_correlation_id: Optional[str] = None
        self._prev_blueprint_id: Optional[str] = None
    
    def __enter__(self):
        self._prev_correlation_id = get_correlation_id()
        self._prev_blueprint_id = get_blueprint_id()
        
        set_correlation_id(self.correlation_id)
        if self.blueprint_id:
            set_blueprint_id(self.blueprint_id)
        
        return self.correlation_id
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        set_correlation_id(self._prev_correlation_id)
        set_blueprint_id(self._prev_blueprint_id)
