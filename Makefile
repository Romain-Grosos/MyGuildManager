# Makefile for MyGuildManager Discord Bot

.PHONY: help install run test test-coverage clean update-imports check-env lint typecheck format logs

# Default target
help:
	@echo "Available commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make run          - Run the bot"
	@echo "  make test         - Run tests"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make lint         - Run linting checks"
	@echo "  make typecheck    - Run type checking"
	@echo "  make format       - Format code with black"
	@echo "  make clean        - Clean cache and temporary files"
	@echo "  make update-imports - Update imports in all cogs"
	@echo "  make logs         - Show recent bot logs"
	@echo "  make check-env    - Check if .env file exists"

# Install dependencies
install:
	pip install -r requirements.txt

# Run the bot
run: check-env
	python run_bot.py

# Run tests
test:
	python -m pytest tests/

# Run tests with coverage
test-coverage:
	python tests/run_tests_with_coverage.py

# Clean cache and temporary files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf htmlcov/ 2>/dev/null || true
	rm -rf .pytest_cache/ 2>/dev/null || true

# Update imports in all cogs
update-imports:
	python scripts/update_cog_imports.py

# Linting checks
lint:
	@echo "Running flake8..."
	@flake8 app/ --count --select=E9,F63,F7,F82 --show-source --statistics
	@echo "✅ Linting passed"

# Type checking
typecheck:
	@echo "Running mypy..."
	@mypy app/ --ignore-missing-imports
	@echo "✅ Type checking passed"

# Format code
format:
	@echo "Formatting with black..."
	@black app/ tests/ scripts/
	@echo "✅ Code formatted"

# Show recent logs
logs:
	@if [ -f logs/discord-bot.log ]; then \
		tail -50 logs/discord-bot.log; \
	else \
		echo "No log file found at logs/discord-bot.log"; \
	fi

# Check if .env file exists
check-env:
	@if [ ! -f app/.env ]; then \
		echo "Error: app/.env file not found!"; \
		echo "Please copy .env.example to app/.env and configure it"; \
		exit 1; \
	fi