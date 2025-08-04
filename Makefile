# Makefile for MyGuildManager Discord Bot

.PHONY: help install run test clean update-imports check-env

# Default target
help:
	@echo "Available commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make run          - Run the bot"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Clean cache and temporary files"
	@echo "  make update-imports - Update imports in all cogs"
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

# Check if .env file exists
check-env:
	@if [ ! -f app/.env ]; then \
		echo "Error: app/.env file not found!"; \
		echo "Please copy .env.example to app/.env and configure it"; \
		exit 1; \
	fi