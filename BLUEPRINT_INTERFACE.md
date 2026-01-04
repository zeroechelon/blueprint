# Blueprint Interface Specification v1.1

> **Cross-Project API Contract for AI-Powered Roadmap Generation**

This document enables any project to invoke Blueprint's generation pipeline to transform goals into structured, executable roadmaps.

---

## ⛔ CRITICAL: Blueprint is a Compiler, Not a Template

**DO NOT manually write Blueprint-format documents.**

If you are an AI agent reading this specification:

### ❌ WRONG Approach
```
1. Read BLUEPRINT_SPEC.md
2. Understand the YAML format
3. Write my own Blueprint manually
4. → INVALID OUTPUT (bypasses all guarantees)
```

### ✅ CORRECT Approach
```
1. Install Blueprint: pip install blueprint-ai
2. Call the API: blueprint.generator.generate_blueprint(goal)
3. Receive validated, optimized Blueprint
4. → VALID OUTPUT (full compilation guarantees)
```

### Why This Matters

Blueprint's value is NOT the Markdown format. It's the **compilation pipeline**:

| Stage | What It Does | Manual Generation |
|-------|--------------|-------------------|
| Decomposition | LLM breaks goal into optimal atomic tasks | ❌ You guess |
| Interface Inference | Determines input/output contracts | ❌ You guess |
| Dependency Analysis | Detects cycles, finds parallelization | ❌ You might miss cycles |
| Validation | Pre-flight checks before execution | ❌ Skipped entirely |
| Test Generation | Creates verification commands | ❌ Generic or missing |

**Manually written Blueprints will:**
- Fail validation checks
- Have suboptimal task decomposition
- Miss interface mismatches
- Contain dependency errors
- Lack proper test coverage

### If You Cannot Install Blueprint

If network restrictions or other constraints prevent installation:

1. **Inform the user** that Blueprint generation requires the Blueprint compiler
2. **Do NOT attempt manual generation** — it produces invalid output
3. **Suggest alternatives:**
   - User installs Blueprint locally and provides output
   - User enables network access for pip install
   - Use a different planning approach (but don't call it a "Blueprint")

### Detection of Invalid Blueprints

Legitimate Blueprint-generated documents contain:
- `_blueprint_version` metadata field
- `_generated_at` timestamp
- `_generator: blueprint.generator` marker

Documents without these markers are considered **manually generated** and may fail validation.

---

## Quick Start

### Prerequisites

Blueprint requires:
- Python 3.11+
- `ANTHROPIC_API_KEY` environment variable
- Blueprint package installed: `pip install blueprint-ai`

### Generate a Blueprint (CLI)

```bash
# Basic generation
blueprint generate "Build a user management system with roles and permissions"

# Save to file
blueprint generate "Build a user management system" -o roadmap.md

# Verbose mode (shows pipeline stages)
blueprint generate "Build a user management system" -v
```

### Generate a Blueprint (Python API)

```python
from blueprint.generator import generate_blueprint

# Simple goal
markdown = generate_blueprint("Build a REST API for user authentication")

# With context about current state
markdown = generate_blueprint(
    goal="Add role-based access control to existing user system",
    context="""
    Current State:
    - User model exists with: id, email, password_hash, created_at
    - Auth endpoints: POST /login, POST /register, GET /me
    - No role/permission system
    - Using PostgreSQL + SQLAlchemy
    - FastAPI framework
    
    Desired End State:
    - Role model (admin, editor, viewer)
    - Permission model (can_create, can_edit, can_delete, can_view)
    - Role assignment to users
    - Permission checks on all endpoints
    - Admin UI for role management
    """
)

print(markdown)
```

---

## API Reference

### `generate_blueprint(goal, context=None, project_name=None, owner=None)`

Generates a complete Blueprint from a natural language goal.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `goal` | `str` | Yes | Natural language description of desired end state |
| `context` | `str` | No | Current state, tech stack, constraints |
| `project_name` | `str` | No | Name for the Blueprint (auto-derived if not provided) |
| `owner` | `str` | No | Document owner (default: "Technical Operations") |

**Returns:** `str` — Complete Blueprint in markdown format (Blueprint Standard Format v0.1)

**Raises:**
- `GenerationError` — If LLM calls fail after retries
- `AssemblyError` — If task count exceeds 100 (Linker threshold)

---

## Pipeline Stages

Blueprint generation uses a 3-stage LLM pipeline:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  GoalDecomposer │───►│ InterfaceInferrer│───►│ BlueprintAssembler│
│                 │    │                  │    │                   │
│ Breaks goal     │    │ Adds input/output│    │ Produces valid    │
│ into atomic     │    │ contracts between│    │ Blueprint markdown│
│ tasks           │    │ tasks            │    │                   │
└─────────────────┘    └──────────────────┘    └───────────────────┘
     Claude API             Claude API              Template + LLM
```

### Stage 1: Goal Decomposition

Breaks the goal into 5-50 atomic tasks with:
- Unique task IDs (T1, T2, ...)
- Dependencies (DAG structure)
- Estimated sessions
- Acceptance criteria
- Files to create/modify

### Stage 2: Interface Inference

For each task, infers:
- **Input**: What data/artifacts this task consumes
- **Output**: What data/artifacts this task produces

This ensures type compatibility across the dependency graph.

### Stage 3: Blueprint Assembly

Produces a complete Blueprint Standard Format document with:
- Metadata (version, generation timestamp, generator marker)
- Tasks organized into tiers (by dependency depth)
- Interface contracts
- Test commands and rollback commands
- Dependency graph visualization

---

## Integration Examples

### Example 1: Geaux File — User Management System

```python
from blueprint.generator import generate_blueprint

# Describe current state and goal
context = """
CURRENT STATE (Geaux File Admin Console):
- DynamoDB tables: customers, filings, activities
- Lambda functions for CRUD operations
- Cognito for authentication (email/password)
- React admin dashboard (basic)
- No user roles or permissions
- Single admin user hardcoded

TECH STACK:
- AWS: DynamoDB, Lambda, Cognito, API Gateway
- Frontend: React + Tailwind
- Backend: Python 3.11
- IaC: CDK (TypeScript)

CONSTRAINTS:
- Must use existing Cognito user pool
- Cannot migrate away from DynamoDB
- Admin console is internal-only (no public access)
"""

goal = """
Build a complete user management system for the Geaux File admin console:
1. Role-based access control (Owner, Admin, Operator, Viewer)
2. User invitation flow (email-based)
3. Permission matrix UI for role configuration
4. Audit logging for all admin actions
5. Self-service password reset
6. Session management with forced logout capability
"""

# Generate the roadmap
blueprint_md = generate_blueprint(goal, context=context, project_name="Geaux File RBAC")

# Save to project
with open("docs/RBAC_ROADMAP.md", "w") as f:
    f.write(blueprint_md)
```

### Example 2: Generic Project

```python
from blueprint.generator import generate_blueprint

goal = "Build a REST API for inventory management with CRUD operations"
context = "Using Python FastAPI, PostgreSQL, and Docker"

blueprint_md = generate_blueprint(goal, context=context)
```

---

## Output Format

Blueprint generates documents in **Blueprint Standard Format v0.1** with generation metadata:

```markdown
# Project Name — Master Roadmap

> **Document Status**: Living Document (Blueprint Standard Format v0.1)
> **Last Updated**: 2026-01-03
> **Owner**: Technical Operations

<!-- BLUEPRINT METADATA (DO NOT REMOVE) -->
<!-- _blueprint_version: 1.2.0 -->
<!-- _generated_at: 2026-01-03T19:50:00Z -->
<!-- _generator: blueprint.generator -->
<!-- END METADATA -->

---

## Strategic Vision

[Goal description]

---

## Tier 0: Foundation

### T1: Task Name

```yaml
task_id: T1
name: "Task Name"
status: 🔲 NOT_STARTED
dependencies: []

interface:
  input: "None (entry point)"
  output: "Artifact description"

files_to_create:
  - path/to/file.py

acceptance_criteria:
  - Criterion 1
  - Criterion 2

test_command: |
  pytest tests/test_t1.py

rollback: "git checkout HEAD~1 -- path/to/file.py"
```

---

## Dependency Graph

```
T1 (entry point)
T1 ─► T2
T2 ─► T3, T4
T3, T4 ─► T5
```
```

---

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `ANTHROPIC_API_KEY not provided` | Missing API key | Set environment variable |
| `Task count exceeds Linker threshold` | Goal too large (>100 tasks) | Break into sub-goals |
| `GenerationError: API rate limit` | Too many requests | Wait and retry |
| `InferenceError: Failed to parse response` | LLM output malformed | Retry with different phrasing |

---

## Best Practices

### Writing Effective Goals

**Good:**
```
"Build a user authentication system with email/password login, 
OAuth2 social login (Google, GitHub), password reset via email,
and session management with JWT tokens"
```

**Bad:**
```
"Add login"  # Too vague, will produce minimal output
```

### Providing Context

Include:
- Current state (what exists today)
- Tech stack (languages, frameworks, databases)
- Constraints (must use X, cannot change Y)
- Team context (solo dev, team of 3, etc.)

### Task Count Guidelines

| Complexity | Expected Tasks | Example |
|------------|---------------|---------|
| Small feature | 5-15 | Add password reset |
| Medium feature | 15-30 | User management system |
| Large feature | 30-50 | Complete auth overhaul |
| Epic | 50-100 | New product module |
| Too large | >100 | Break into sub-Blueprints |

---

## Programmatic Usage

### As a Library

```python
# Low-level access to pipeline stages
from blueprint.generator.decomposer import GoalDecomposer
from blueprint.generator.interface_inferrer import InterfaceInferrer
from blueprint.generator.assembler import BlueprintAssembler

# Stage 1: Decompose
decomposer = GoalDecomposer()
tasks = decomposer.decompose(goal, context=context)

# Stage 2: Infer interfaces  
inferrer = InterfaceInferrer()
enriched_tasks = inferrer.infer(tasks)

# Stage 3: Assemble
assembler = BlueprintAssembler()
markdown = assembler.assemble(enriched_tasks, goal)
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-03 | Initial release with generation pipeline |
| 1.1 | 2026-01-03 | Added anti-bypass warning, generation metadata |

---

## Related Documents

- [BLUEPRINT_SPEC.md](docs/BLUEPRINT_SPEC.md) — Blueprint Standard Format specification
- [SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) — Internal architecture
- [PUBLIC_RELEASE_PROCEDURE.md](docs/procedures/PUBLIC_RELEASE_PROCEDURE.md) — Release process

---

> Built with [zeOS](https://github.com/rgsuarez/zeOS) — the persistence-first operating system for AI collaboration.

*Blueprint v1.2.0 — "Goals become roadmaps"*
