# Example Project — Blueprint

> **Document Status**: Draft
> **Last Updated**: 2026-01-03
> **Owner**: Test User

---

## Strategic Vision

Build a simple todo CLI application with add, list, and remove functionality.

---

## Success Metrics

| Metric | Target | Validation |
|--------|--------|------------|
| Command latency | <100ms | Benchmark suite |
| Test coverage | >80% | pytest-cov |

---

## Tier 0: Foundation

**Goal**: Set up project structure

### T0.1: Project Setup

```yaml
task_id: T0.1
name: "Initialize project"
status: 🔲 NOT_STARTED
dependencies: []

interface:
  input: "None (entry point)"
  output: "Initialized Python project"

acceptance_criteria:
  - pyproject.toml exists
  - src/ directory created

test_command: |
  python -c "import todo"

rollback: "rm -rf src pyproject.toml"
```

### T0.2: Add Dependencies

```yaml
task_id: T0.2
name: "Add click dependency"
status: 🔲 NOT_STARTED
dependencies: [T0.1]

interface:
  input: "Initialized project from T0.1"
  output: "Project with click installed"

acceptance_criteria:
  - click in dependencies
  - pip install succeeds

test_command: |
  pip install -e . && python -c "import click"

rollback: "git checkout HEAD~1 -- pyproject.toml"
```

---

## Tier 1: Core Features

**Goal**: Implement todo operations

### T1.1: Add Command

```yaml
task_id: T1.1
name: "Implement add command"
status: 🔲 NOT_STARTED
dependencies: [T0.2]

interface:
  input: "Task description string"
  output: "Task added to storage"

files_to_create:
  - src/todo/cli.py
  - src/todo/storage.py

acceptance_criteria:
  - todo add "task" creates task
  - Tasks persist to file

test_command: |
  python -m pytest tests/test_add.py

rollback: "git checkout HEAD~1 -- src/todo/"
```

---

## Dependency Graph

```
T0.1 ─► T0.2 ─► T1.1
```

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-01-03 | Test | Initial |
