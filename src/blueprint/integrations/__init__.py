"""Blueprint Integrations - connects to external systems.

Components:
- outpost: Multi-agent dispatch via SSM (T3.1)
- aggregator: Result collection from S3 (T3.2)

Note: These modules require the 'outpost' optional dependencies.
Install with: pip install blueprint[outpost]
"""


def __getattr__(name: str):
    """Lazy import to avoid requiring optional dependencies at import time."""
    # Outpost exports
    outpost_exports = (
        "OutpostDispatcher", "DispatchResult", "DispatchStatus", 
        "DispatchError", "create_dispatcher", "DEFAULT_BUCKET", 
        "DEFAULT_SSM_INSTANCE"
    )
    if name in outpost_exports:
        from blueprint.integrations import outpost
        return getattr(outpost, name)
    
    # Aggregator exports
    aggregator_exports = (
        "ResultAggregator", "AggregationResult", "AggregationStatus",
        "AggregationError", "ArtifactInfo", "ConflictInfo", 
        "DownloadFailure", "create_aggregator"
    )
    if name in aggregator_exports:
        from blueprint.integrations import aggregator
        return getattr(aggregator, name)
    
    raise AttributeError(f"module 'blueprint.integrations' has no attribute '{name}'")


__all__ = [
    # Dispatcher (T3.1)
    "OutpostDispatcher",
    "DispatchResult",
    "DispatchStatus",
    "DispatchError",
    "create_dispatcher",
    # Aggregator (T3.2)
    "ResultAggregator",
    "AggregationResult",
    "AggregationStatus",
    "AggregationError",
    "ArtifactInfo",
    "ConflictInfo",
    "DownloadFailure",
    "create_aggregator",
    # Constants
    "DEFAULT_BUCKET",
    "DEFAULT_SSM_INSTANCE",
]
