# Contributing to velmax

Thank you for your interest in contributing! This document outlines the process for contributing to the project.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- Docker (optional, for Firecrawl integration)

### Development Setup

```bash
# Clone the repository
git clone https://github.com/<your-username>/velmax.git
cd velmax

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install in development mode with all extras
pip install -e ".[dev,all]"

# Install pre-commit hooks
pre-commit install
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Write clear, focused commits
- Follow the code style (see below)
- Add tests for new functionality
- Update documentation as needed

### 3. Run Tests Locally

```bash
# Run linting
ruff check .

# Run type checking
mypy scraper/

# Run tests
pytest tests/ -x -q --tb=short

# Run with coverage
pytest tests/ --cov=scraper --cov-report=term-missing
```

### 4. Submit a Pull Request

- Push your branch to your fork
- Open a PR against `main`
- Fill out the PR template
- Ensure CI passes

## Code Style

### Python

- **Formatter**: Ruff (configured in `pyproject.toml`)
- **Type Checking**: MyPy (configured in `pyproject.toml`)
- **Line Length**: 100 characters
- **Python Version**: 3.10+

Run formatting:
```bash
ruff check . --fix
ruff format .
```

### Commit Messages

Follow conventional commits:
```
type(scope): description

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`

Examples:
```
feat(extraction): add support for nested JSON schemas
fix(validator): handle None schema gracefully
docs(readme): update installation instructions
test(fallback): add test for engine circuit breaker
```

## Testing Guidelines

### Test Structure

```
tests/
├── unit/           # Fast, isolated unit tests
├── integration/    # Slower integration tests (marked @pytest.mark.integration)
└── fixtures/       # Shared test fixtures
```

### Writing Tests

- Use `pytest-asyncio` for async tests
- Mock external services (APIs, databases)
- Use fixtures for common setup
- Test both success and failure paths

Example:
```python
@pytest.mark.asyncio
async def test_engine_selector_prefers_local(mock_engines):
    selector = SmartEngineSelector(config)
    engine, _ = selector.select(profile, request)
    assert engine == EngineType.HTTP
```

### Running Specific Tests

```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# Specific test
pytest tests/integration/test_research_mode.py::test_regular_url_request -v

# With coverage
pytest tests/ --cov=scraper --cov-report=html
```

## Documentation

- Update `README.md` for user-facing changes
- Update docstrings for API changes
- Add examples for new features
- Keep `CHANGELOG.md` updated

## Release Process

Maintainers only:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
2. Create release tag: `git tag vX.Y.Z`
3. Push tag: `git push origin vX.Y.Z`
4. GitHub Actions handles PyPI and Docker publishing

## Reporting Issues

- Use GitHub Issues
- Search existing issues first
- Provide minimal reproduction case
- Include environment details (OS, Python version, dependencies)

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Questions?

Open a GitHub Discussion or ask in a PR.