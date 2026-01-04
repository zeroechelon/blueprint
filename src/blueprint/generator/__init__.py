"""Blueprint Generator - transforms goals into Blueprint specifications.

Components:
- decomposer: Breaks goals into atomic tasks (T2.1)
- interface_inferrer: Infers input/output contracts (T2.2)
- assembler: Produces Blueprint markdown (T2.3)

Note: These modules require the 'llm' optional dependencies.
Install with: pip install blueprint[llm]

Usage:
    from blueprint.generator import generate_blueprint
    
    markdown = generate_blueprint(
        goal="Build a REST API for user authentication",
        context="Using FastAPI and PostgreSQL"
    )
"""
from typing import Optional


def generate_blueprint(
    goal: str,
    context: Optional[str] = None,
    project_name: Optional[str] = None,
    owner: str = "Technical Operations",
    api_key: Optional[str] = None,
) -> str:
    """Generate a complete Blueprint from a natural language goal.
    
    This is the primary entry point for Blueprint generation. It orchestrates
    the full pipeline: decomposition → interface inference → assembly.
    
    Args:
        goal: Natural language description of desired end state.
        context: Optional context about current state, tech stack, constraints.
        project_name: Name for the Blueprint (auto-derived from goal if not provided).
        owner: Document owner name (default: "Technical Operations").
        api_key: Anthropic API key (falls back to ANTHROPIC_API_KEY env var).
    
    Returns:
        Complete Blueprint in markdown format (Blueprint Standard Format v0.1).
    
    Raises:
        DecompositionError: If goal decomposition fails.
        InferenceError: If interface inference fails.
        AssemblyError: If assembly fails or task count exceeds 100.
    
    Example:
        >>> from blueprint.generator import generate_blueprint
        >>> 
        >>> markdown = generate_blueprint(
        ...     goal="Build user authentication with OAuth2",
        ...     context="FastAPI backend, PostgreSQL database"
        ... )
        >>> print(markdown[:100])
        '# User Authentication — Master Roadmap...'
    """
    from blueprint.generator.decomposer import GoalDecomposer
    from blueprint.generator.interface_inferrer import InterfaceInferrer
    from blueprint.generator.assembler import BlueprintAssembler
    
    # Build context-enriched goal if context provided
    full_goal = goal
    if context:
        full_goal = f"{goal}\n\nContext:\n{context}"
    
    # Stage 1: Decompose goal into tasks
    decomposer = GoalDecomposer(api_key=api_key)
    tasks = decomposer.decompose(full_goal, return_dicts=True)
    
    # Stage 2: Infer interface contracts
    inferrer = InterfaceInferrer(api_key=api_key)
    enriched_tasks = inferrer.infer(tasks, project_context=context)
    
    # Stage 3: Assemble into Blueprint markdown
    assembler = BlueprintAssembler(api_key=api_key)
    markdown = assembler.assemble(
        enriched_tasks,
        goal=goal,  # Use original goal for vision section
        project_name=project_name,
        owner=owner,
    )
    
    return markdown


def __getattr__(name: str):
    """Lazy import to avoid requiring optional dependencies at import time."""
    # Top-level convenience function
    if name == "generate_blueprint":
        return generate_blueprint
    
    # Decomposer exports
    if name in ("GoalDecomposer", "decompose_goal", "DecompositionError", "MODEL_OPUS", "MODEL_SONNET"):
        from blueprint.generator import decomposer
        return getattr(decomposer, name)
    
    # Interface inferrer exports
    if name in ("InterfaceInferrer", "infer_interfaces", "InferenceError"):
        from blueprint.generator import interface_inferrer
        return getattr(interface_inferrer, name)
    
    # Assembler exports
    if name in ("BlueprintAssembler", "assemble_blueprint", "AssemblyError", "LINKER_THRESHOLD"):
        from blueprint.generator import assembler
        return getattr(assembler, name)
    
    raise AttributeError(f"module 'blueprint.generator' has no attribute '{name}'")


__all__ = [
    # Primary API
    "generate_blueprint",
    # Decomposer (T2.1)
    "GoalDecomposer",
    "decompose_goal", 
    "DecompositionError",
    # Interface Inferrer (T2.2)
    "InterfaceInferrer",
    "infer_interfaces",
    "InferenceError",
    # Assembler (T2.3)
    "BlueprintAssembler",
    "assemble_blueprint",
    "AssemblyError",
    "LINKER_THRESHOLD",
    # Models
    "MODEL_OPUS",
    "MODEL_SONNET",
]
