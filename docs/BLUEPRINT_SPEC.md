# Blueprint Standard Format Specification

> **Version**: 0.1.0 (Draft)
> **Status**: In Development
> **Last Updated**: 2026-01-03

---

## Overview

The Blueprint Standard Format (BSF) defines a structured, machine-parseable specification for AI agent orchestration. A Blueprint is both human-readable documentation and executable instruction set.

**Design Principles** (Fleet-Validated):
1. Interface-First, Not Instruction-First
2. Compilable (Pre-flight validation possible)
3. Structured Format (Markdown + YAML/JSON blocks)
4. Built-in Verification (Every task is testable)
5. Human-in-the-Loop Signals (Explicit pause points)

---

## Document Structure

A Blueprint document consists of:

```markdown
# {Project Name} — {Document Type}

> **Document Status**: {status}
> **Last Updated**: {date}
> **Owner**: {owner}

---

## Strategic Vision
{Natural language description of the goal}

---

## Success Metrics
{Table of measurable outcomes}

---

## Tier N: {Phase Name}

### {Task ID}: {Task Name}

\```yaml
task_id: {unique_id}
name: "{human readable name}"
status: {status_enum}
# ... task block fields
\```

---

## Dependency Graph
{Visual or textual DAG representation}

---

## Document Control
{Version history}
```

---

## Task Block Schema

Every task is defined in a YAML code block with the following fields:

### Required Fields

```yaml
task_id: string        # Unique identifier (e.g., "T1.2")
name: string           # Human-readable task name
status: enum           # 🔲 NOT_STARTED | 🔄 IN_PROGRESS | ✅ COMPLETE | ⛔ BLOCKED
dependencies: list     # Task IDs this depends on (empty list if none)

interface:
  input: string        # Description of required input
  output: string       # Description of produced output

acceptance_criteria:   # List of testable conditions
  - string
  - string

test_command: string   # Shell command that returns 0 on success

rollback: string       # Command to undo this task's changes
```

### Optional Fields

```yaml
assignee: string|null           # Agent or human assigned
estimated_sessions: integer     # Estimated work sessions
files_to_create: list           # Files this task will produce
files_to_modify: list           # Existing files to change

human_required:                 # Pause point for human action
  action: string                # What the human must do
  reason: string                # Why it's needed
  notify:
    channel: string             # "email" | "slack" | "webhook" | "env"
    recipient: string           # Destination or variable name
  timeout: string               # Duration before timeout action
  on_timeout: string            # "ABORT" | "SKIP" | "CONTINUE"
  on_missing: string            # For env vars: action if not set

example: object                 # Example input/output for clarity
notes: string                   # Additional context
```

---

## Status Enumeration

| Status | Icon | Meaning |
|--------|------|---------|
| NOT_STARTED | 🔲 | Task has not begun |
| IN_PROGRESS | 🔄 | Task is actively being worked |
| COMPLETE | ✅ | Task finished and verified |
| BLOCKED | ⛔ | Task cannot proceed (dependency or human required) |
| SKIPPED | ⏭️ | Task intentionally bypassed |

---

## Interface Contract

The `interface` block defines the data contract between tasks:

```yaml
interface:
  input: "Parsed Blueprint object (Python dataclass)"
  output: "Validation result with errors list"
```

**Rules**:
1. A task's `input` must be satisfiable by its dependencies' `output`
2. The validator checks interface compatibility across the DAG
3. Type mismatches are pre-flight failures

---

## Verification Block

Every task MUST include a `test_command`:

```yaml
test_command: |
  cd src && python3 -m pytest tests/test_parser.py -v
```

**Rules**:
1. Must be executable shell command
2. Exit code 0 = pass, non-zero = fail
3. Should be runnable independently
4. "Done" = test passes, not "prose complete"

---

## HUMAN_REQUIRED Block

When a task requires human intervention:

```yaml
human_required:
  action: "Provide Anthropic API key"
  reason: "Required for Claude integration in goal decomposition"
  notify:
    channel: "env"
    variable: "ANTHROPIC_API_KEY"
  on_missing: "ABORT with setup instructions"
```

### Notification Channels

| Channel | Fields | Behavior |
|---------|--------|----------|
| `email` | `recipient` | Send email notification |
| `slack` | `channel`, `webhook` | Post to Slack |
| `webhook` | `url` | HTTP POST to endpoint |
| `env` | `variable(s)` | Check environment variable |
| `console` | — | Print to stdout |

### Timeout Behaviors

| Action | Meaning |
|--------|---------|
| `ABORT` | Stop execution, fail the Blueprint |
| `SKIP` | Mark task skipped, continue with dependents |
| `CONTINUE` | Proceed without human input (use default) |

---

## Dependency Graph

Blueprints should include a visual dependency graph:

```
T0.1 ─┬─► T0.2 ─┬─► T0.3
      │         └─► T0.4
      └─► T1.1 ─► T1.2 ─► T1.3
```

Or machine-readable format:

```yaml
dependencies:
  T0.2: [T0.1]
  T0.3: [T0.2]
  T0.4: [T0.2]
  T1.1: [T0.1]
  T1.2: [T1.1]
  T1.3: [T1.2]
```

---

## Validation Rules

A Blueprint is **valid** if:

1. ✅ All task_ids are unique
2. ✅ All dependency references exist
3. ✅ No circular dependencies
4. ✅ All required fields present
5. ✅ Interface contracts are compatible
6. ✅ All test_commands are non-empty
7. ✅ All rollback commands are non-empty

---

## Example Task Block

```yaml
task_id: T1.2
name: "Implement Blueprint validator"
status: 🔲 NOT_STARTED
assignee: null
estimated_sessions: 2
dependencies: [T1.1]

interface:
  input: "Parsed Blueprint object (from parser.py)"
  output: "ValidationResult(passed: bool, errors: List[str])"

files_to_create:
  - src/blueprint/validator.py
  - tests/test_validator.py

acceptance_criteria:
  - Validator detects circular dependencies
  - Validator detects missing dependency references
  - Validator detects interface mismatches
  - Validator returns actionable error messages

test_command: |
  cd src && python3 -m pytest tests/test_validator.py -v

rollback: "git checkout HEAD~1 -- src/blueprint/validator.py"

notes: "Should complete in under 2 hours for experienced Python developer"
```

---

## File Format

- **Extension**: `.md` (Markdown)
- **Encoding**: UTF-8
- **YAML blocks**: Fenced with triple backticks and `yaml` language tag

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-01-03 | Initial draft specification |

---

*Blueprint Standard Format v0.1.0*
*"Bytecode for AI agents"*
