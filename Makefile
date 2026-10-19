# These names are commands, not files whose timestamps should control execution.
.PHONY: install init up down logs doctor run test

# Install the controller and development tools in a project-local environment.
# Explicit interpreter paths avoid depending on an activated shell environment.
install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'

# Generate credentials using only the standard library. Existing .env is kept.
init:
	python3 scripts/init_env.py

# Build infrastructure, start it in the background, and wait for readiness.
# The long wait budget accommodates the initial Langfuse database migrations.
up:
	docker compose up -d --build --wait --wait-timeout 600

# Stop this Compose stack while preserving its named database/storage volumes.
down:
	docker compose down

# Follow infrastructure stdout/stderr. Workload command output is streamed by
# the Python runner and saved separately under the ignored runs/ directory.
logs:
	docker compose logs -f opensandbox langfuse-web langfuse-worker

# Check authenticated service connectivity without launching an experiment.
doctor:
	.venv/bin/agents-sandbox doctor

# Execute the default one-task, one-step deterministic Harness2 experiment.
run:
	.venv/bin/agents-sandbox run

# Run offline integration tests with simulated services and in-memory traces.
test:
	.venv/bin/python -m pytest -q
