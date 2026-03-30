# Contributing to DamascusTransit

Thank you for your interest in contributing to DamascusTransit! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.11+
- A [Supabase](https://supabase.com) account (free tier)
- Docker (optional, for containerized development)

### Local Development

```bash
# Clone the repository
git clone https://github.com/actuatorsos/SyrianTransitSystem.git
cd SyrianTransitSystem

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and configure
cp .env.example .env
# Edit .env with your Supabase credentials

# Run the development server
uvicorn api.index:app --reload --port 8000
```

### Database Setup

1. Create a Supabase project
2. Enable PostGIS: `CREATE EXTENSION IF NOT EXISTS postgis;`
3. Run `db/schema.sql` in the SQL Editor
4. Run `db/seed.sql` to load sample data

### Running Tests

```bash
# Run the test suite
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=api --cov-report=term-missing

# Load testing (requires running server)
locust -f tests/locustfile.py --host http://localhost:8000
```

## How to Contribute

### Reporting Bugs

- Open an issue with a clear title and description
- Include steps to reproduce the bug
- Include the expected vs actual behavior
- Note the environment (OS, Python version, browser)

### Suggesting Features

- Open an issue with the `enhancement` label
- Describe the use case and why it would benefit the project
- If possible, outline a proposed implementation approach

### Submitting Pull Requests

1. **Fork** the repository and create a branch from `main`
2. **Name your branch** descriptively: `fix/cors-localhost`, `feat/websocket-support`, `docs/api-examples`
3. **Write or update tests** for your changes
4. **Follow existing code style** — the codebase uses standard Python conventions
5. **Keep PRs focused** — one feature or fix per PR
6. **Write a clear PR description** explaining what changed and why

### Code Style

- Python: Follow PEP 8, use type hints where practical
- SQL: Uppercase keywords, lowercase identifiers
- HTML/JS: 2-space indentation, vanilla JS (no frameworks)
- Commit messages: Use imperative mood (`Add feature`, not `Added feature`)

### Areas Where Help Is Needed

- **Testing** — Expanding test coverage for all 26 API endpoints
- **Security** — Input validation, SQL injection prevention, password complexity
- **Performance** — Query optimization, connection pooling strategies
- **Accessibility** — ARIA labels, keyboard navigation, screen reader support
- **Localization** — Improving Arabic translations, adding new languages
- **Documentation** — API usage examples, architecture diagrams, tutorials
- **Mobile** — Improving PWA offline capabilities and UX

## Project Structure

| Directory | Contents |
|-----------|----------|
| `api/` | FastAPI backend (main application) |
| `db/` | SQL schema, seed data, GTFS feed |
| `public/` | Frontend applications (HTML + JS) |
| `tests/` | Pytest tests, contract tests, load tests |
| `scripts/` | Deployment and setup scripts |
| `lib/` | Shared Python utilities |

## Communication

- **Issues**: Use GitHub Issues for bugs, features, and questions
- **Pull Requests**: Use PR comments for code review discussion

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
