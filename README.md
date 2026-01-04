# Blueprint

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Specification compiler for AI agent orchestration.**

Blueprint transforms natural language goals into structured, compilable, interface-first contracts that any AI agent can execute with deterministic results.

## Why Blueprint?

As AI coding agents become mainstream, the bottleneck shifts from "knowing programming languages" to "articulating clear, executable instructions." Natural language is expressive but ambiguous — and ambiguity compounds catastrophically with parallel agents.

Blueprint solves this by compiling goals into **structured specifications** with:
- **Interface contracts** between tasks (input/output types)
- **Dependency graphs** (DAG structure for parallelization)
- **Built-in verification** (test commands, acceptance criteria)
- **Human-in-the-loop signals** (explicit pause points)

## Installation

```bash
pip install blueprint-ai
```

Or with LLM support for generation features:
```bash
pip install blueprint-ai[llm]
```

### Requirements
- Python 3.11+
- `ANTHROPIC_API_KEY` environment variable (for generation features)

## Quick Start

### Generate a Blueprint from a Goal

```bash
export ANTHROPIC_API_KEY="your-key"
blueprint generate "Build a user authentication system with JWT tokens"
```

```python
from blueprint.generator import generate_blueprint

roadmap = generate_blueprint(
    goal="Build a user authentication system with JWT tokens",
    context="Using FastAPI and PostgreSQL"
)
print(roadmap)
```

### Validate an Existing Blueprint

```bash
blueprint validate my_roadmap.md
```

### Execute a Blueprint (Dry Run)

```bash
blueprint execute my_roadmap.md --dry-run
```

## ⚠️ Important: Blueprint is a Compiler, Not a Template

**DO NOT manually write Blueprint format documents.**

Blueprint's value comes from LLM-powered decomposition, interface inference, and validation. Manual generation bypasses these guarantees.

**Always use the `blueprint generate` command or Python API.**

## Documentation

- [Blueprint Specification](docs/BLUEPRINT_SPEC.md) — Format reference
- [System Architecture](docs/SYSTEM_ARCHITECTURE.md) — Internal design
- [API Interface](BLUEPRINT_INTERFACE.md) — Integration guide

## License

Apache 2.0 — See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting PRs.

---

*Blueprint — "Goals become roadmaps"*
