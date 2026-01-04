# Contributing to Blueprint

Thank you for your interest in contributing to Blueprint!

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest tests/ -v`)
5. Run linting (`ruff check src/`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## Development Setup

```bash
git clone https://github.com/zeroechelon/blueprint.git
cd blueprint
pip install -e ".[dev]"
```

## Code Style

- We use `ruff` for linting
- Type hints are required for public APIs
- Docstrings follow Google style

## Testing

```bash
pytest tests/ -v --cov=blueprint
```

## License

By contributing, you agree that your contributions will be licensed under Apache 2.0.
