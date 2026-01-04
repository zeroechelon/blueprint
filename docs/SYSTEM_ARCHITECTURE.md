# Blueprint — System Architecture

> **Document Status**: Living Document
> **Last Updated**: 2026-01-03
> **Owner**: Technical Operations

---

## Overview

Blueprint is a specification compiler that transforms goals into structured, compilable, interface-first contracts for AI agent orchestration.

```
┌──────────────────────────────────────────────────────────────┐
│                        BLUEPRINT                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────┐    ┌───────────┐    ┌──────────┐              │
│  │  GOAL   │───►│ GENERATOR │───►│ BLUEPRINT │              │
│  │ (NL)    │    │           │    │ (Spec)    │              │
│  └─────────┘    └───────────┘    └────┬─────┘              │
│                                        │                     │
│                                        ▼                     │
│                                 ┌──────────┐                │
│                                 │ VALIDATOR │                │
│                                 └────┬─────┘                │
│                                      │                       │
│                                      ▼                       │
│                               ┌──────────┐                  │
│                               │ EXECUTOR │                  │
│                               └────┬─────┘                  │
│                                    │                         │
│              ┌─────────────────────┼─────────────────────┐  │
│              ▼                     ▼                     ▼  │
│        ┌──────────┐         ┌──────────┐         ┌──────────┐│
│        │ Agent 1  │         │ Agent 2  │         │ Agent N  ││
│        │ (Claude) │         │ (Codex)  │         │ (Gemini) ││
│        └────┬─────┘         └────┬─────┘         └────┬─────┘│
│             │                    │                    │      │
│             └────────────────────┼────────────────────┘      │
│                                  ▼                           │
│                           ┌──────────┐                      │
│                           │AGGREGATOR│                      │
│                           └────┬─────┘                      │
│                                │                             │
│                                ▼                             │
│                           ┌──────────┐                      │
│                           │ RESULT   │                      │
│                           └──────────┘                      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Generator (`src/blueprint/generator/`)

Transforms natural language goals into Blueprint format.

| Component | Purpose |
|-----------|---------|
| `decomposer.py` | Breaks goals into atomic tasks |
| `interface_inferrer.py` | Infers input/output contracts |
| `assembler.py` | Produces Blueprint markdown |

### 2. Compiler (`src/blueprint/`)

Parses and validates Blueprint documents.

| Component | Purpose |
|-----------|---------|
| `parser.py` | Reads Blueprint markdown into objects |
| `models.py` | Pydantic V2 data structures for Blueprint elements |
| `validator.py` | Pre-flight checks before execution |

### 3. Executor (`src/blueprint/`)

Executes Blueprint with dependency awareness.

| Component | Purpose |
|-----------|---------|
| `executor.py` | Orchestrates task execution |
| `scheduler.py` | Determines parallelization strategy |

### 4. Integrations (`src/blueprint/integrations/`)

Connects to external systems.

| Component | Purpose |
|-----------|---------|
| `outpost.py` | Dispatches to Outpost multi-agent fleet |
| `aggregator.py` | Collects and merges parallel results |

---

## Data Flow

```
1. INPUT:  "Build a user authentication system with JWT"
              │
              ▼
2. DECOMPOSE: Goal → [Task1, Task2, ..., TaskN]
              │
              ▼
3. INFER:    Tasks → Tasks with Interface Contracts
              │
              ▼
4. ASSEMBLE: Tasks → Blueprint Markdown Document
              │
              ▼
5. VALIDATE: Blueprint → Validation Result (pass/fail)
              │
              ▼
6. SCHEDULE: Blueprint → Execution Plan (DAG with parallelization)
              │
              ▼
7. DISPATCH: Plan → Agent Tasks (via Outpost)
              │
              ▼
8. AGGREGATE: Results → Unified Output
```

---

## Blueprint Standard Format

See `docs/BLUEPRINT_SPEC.md` for the complete specification.

**Key Elements**:
- **Task Blocks**: Atomic units of work with unique IDs
- **Interface Contracts**: Input/output type declarations
- **Verification Blocks**: Executable test commands
- **HUMAN_REQUIRED Signals**: Pause points for human action
- **BlueprintRef**: References to sub-modules (Linker support)

---

## Hierarchical Compilation (Linker)

Large Blueprints can exceed agent context windows. The **Linker** concept allows Blueprints to reference sub-modules:

```yaml
refs:
  - ref: "./auth-module.bp.md"
    required: true
    inline: false  # Treat as external dependency

  - ref: "./database-schema.bp.md"
    required: true
    inline: true   # Merge tasks into parent Blueprint
```

**Benefits**:
- Only load relevant sections per agent
- Decompose mega-projects into manageable chunks
- Support modular, reusable Blueprint libraries

**Implementation** (T2.3 Assembler):
1. Assembler detects when output exceeds ~100 tasks
2. Prompts for decomposition into sub-modules
3. Generates parent Blueprint with `refs` field
4. Each sub-module is a standalone, valid Blueprint

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Data Models | **Pydantic V2** (robust LLM output validation) |
| CLI | Click or Typer |
| LLM Integration | Anthropic Claude API |
| Agent Dispatch | Outpost (SSM-based, async) |
| Data Format | Markdown + YAML code blocks |
| Testing | pytest |

### Why Pydantic V2?

The Generator (Tier 2) produces Blueprints from LLM outputs, which are inherently "fuzzy":
- String `"2"` instead of int `2` for estimated_sessions
- Missing optional fields
- Malformed enum values like `"ABORT with instructions"`

Pydantic V2 handles all of these with:
- Automatic type coercion
- Field validators for custom parsing
- Graceful error handling with actionable messages
- `model_validate()` for dict → model with validation

---

## Async Outpost Integration

Real-world agents take minutes, not milliseconds. The Outpost dispatcher is **non-blocking**:

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  Blueprint  │      │   Outpost   │      │   Agents    │
│  Executor   │      │  Dispatcher │      │  (Fleet)    │
└──────┬──────┘      └──────┬──────┘      └──────┬──────┘
       │                    │                    │
       │  dispatch(task)    │                    │
       │───────────────────►│                    │
       │                    │   SSM command      │
       │                    │───────────────────►│
       │  command_id        │                    │
       │◄───────────────────│                    │
       │                    │                    │
       │  [continues work]  │                    │
       │                    │                    │ [executes]
       │                    │                    │
       │  poll(command_id)  │                    │
       │───────────────────►│   status?         │
       │                    │───────────────────►│
       │                    │   result          │
       │◄───────────────────│◄──────────────────│
```

**Key Design**:
- `dispatch()` returns immediately with `command_id`
- `poll()` or webhook callback for result retrieval
- Executor continues scheduling independent tasks while waiting

---

## Repository Structure

```
blueprint/
├── src/
│   └── blueprint/
│       ├── __init__.py
│       ├── cli.py              # Entry point
│       ├── parser.py           # Blueprint parser
│       ├── models.py           # Pydantic V2 data structures
│       ├── validator.py        # Pre-flight checks
│       ├── executor.py         # Task orchestration
│       ├── scheduler.py        # Parallelization
│       ├── generator/
│       │   ├── decomposer.py   # Goal breakdown
│       │   ├── interface_inferrer.py
│       │   └── assembler.py    # Blueprint output
│       └── integrations/
│           ├── outpost.py      # Multi-agent dispatch
│           └── aggregator.py   # Result collection
├── tests/
│   └── ...
├── docs/
│   ├── MASTER_ROADMAP.md       # Self-hosting roadmap
│   ├── SYSTEM_ARCHITECTURE.md  # This document
│   └── BLUEPRINT_SPEC.md       # Format specification
├── examples/
│   └── valid_blueprint.json    # Sample Blueprint
├── templates/
│   └── blueprint_template.md   # Generation template
├── schema/
│   └── blueprint_schema_v0.1.0.json
├── session-journals/
│   └── ...
├── .zeos/
│   └── APP_MANIFEST.json
└── pyproject.toml
```

---

## Integration Points

### Outpost

Blueprint integrates with Outpost for multi-agent execution:

```python
# src/blueprint/integrations/outpost.py
async def dispatch_task(task: Task, agent: str) -> str:
    """Dispatch single task to Outpost agent.
    
    Returns command_id immediately (non-blocking).
    """
    pass

async def poll_result(command_id: str) -> TaskResult:
    """Poll for task completion status."""
    pass

async def dispatch_parallel(tasks: List[Task]) -> Dict[str, str]:
    """Dispatch parallelizable tasks simultaneously."""
    pass
```

### zeOS

Blueprint is a zeOS venture:
- SOUL file: `zeOS/apps/blueprint/BLUEPRINT_SOUL.md`
- Session journals: `blueprint/session-journals/`
- Boot command: `!project blueprint`

---

## Security Considerations

1. **No credentials in Blueprints** — API keys are referenced via environment variables
2. **HUMAN_REQUIRED for sensitive operations** — Key provisioning requires human approval
3. **Validation before execution** — Pre-flight checks prevent invalid execution

---

*Last verified: 2026-01-03*
*Architecture version: 0.2.0 (Pydantic migration + Linker concept)*
