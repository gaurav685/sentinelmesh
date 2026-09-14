"""Offline checks on the CI workflow.

The workflow itself can only be proven by running it on GitHub. These assertions
cover the failure modes that would make a green build meaningless — chiefly an
integration job that silently skips because its services never came up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_JOBS = {"static", "unit", "integration", "image", "frontend", "security"}


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(workflow: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return workflow["jobs"][job]["steps"]


def _run_script(workflow: dict[str, Any], job: str) -> str:
    return "\n".join(s.get("run", "") for s in _steps(workflow, job))


def test_workflow_parses_and_defines_the_expected_jobs(workflow: dict[str, Any]):
    assert set(workflow["jobs"]) == EXPECTED_JOBS


def test_workflow_uses_least_privilege_token(workflow: dict[str, Any]):
    assert workflow["permissions"] == {"contents": "read"}


def test_superseded_runs_are_cancelled(workflow: dict[str, Any]):
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_runs_on_push_to_main_and_on_pull_requests(workflow: dict[str, Any]):
    # PyYAML parses the bare key `on` as the boolean True.
    triggers = workflow.get("on") or workflow[True]
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers


def test_static_job_runs_ruff_and_strict_mypy(workflow: dict[str, Any]):
    script = _run_script(workflow, "static")
    assert "ruff check packages services tests migrations scripts" in script
    assert "mypy --strict" in script


def test_unit_job_excludes_integration_and_checks_the_contract_schema(
    workflow: dict[str, Any],
):
    script = _run_script(workflow, "unit")
    assert '-m "not integration"' in script
    assert "gen_contracts.py --check" in script


def test_integration_job_provides_its_backing_services_with_healthchecks(
    workflow: dict[str, Any],
):
    services = workflow["jobs"]["integration"]["services"]
    assert set(services) == {"postgres", "redis", "neo4j"}
    for name in services:
        assert "--health-cmd" in services[name]["options"], name
        assert services[name]["ports"], name


def test_integration_job_refuses_to_pass_by_skipping(workflow: dict[str, Any]):
    """The guard that stops an unreachable database from producing a green build.

    `tests/integration/conftest.py` turns the skip into a failure when this is
    set, so a passing `integration` job always means the tests really executed.
    """
    assert workflow["jobs"]["integration"]["env"]["SM_REQUIRE_INTEGRATION"] == "1"


def test_integration_job_applies_migrations_before_testing(workflow: dict[str, Any]):
    names = [s.get("name") for s in _steps(workflow, "integration")]
    assert names.index("Apply migrations") < names.index("Integration tests")
    assert names.index("Apply Neo4j schema") < names.index("Integration tests")
    script = _run_script(workflow, "integration")
    assert "alembic" in script
    assert "scripts/graph_migrate.py" in script


def test_integration_job_talks_to_localhost_because_it_runs_on_the_runner(
    workflow: dict[str, Any],
):
    """The opposite of the compose rule: service containers publish onto the
    runner's own network, so `localhost` is correct here."""
    env = workflow["jobs"]["integration"]["env"]
    assert env["SM_TEST_PG_HOST"] == "localhost"
    assert env["SM_TEST_REDIS_URL"].startswith("redis://localhost:")
    assert env["SM_TEST_NEO4J_URI"].startswith("bolt://localhost:")


def test_image_job_builds_the_dockerfile_and_asserts_non_root(workflow: dict[str, Any]):
    script = _run_script(workflow, "image")
    assert "docker build -f deploy/docker/Dockerfile.app" in script
    assert "10001" in script, "the image must be checked for a non-root user"


def test_image_job_proves_the_production_config_guard_is_live(workflow: dict[str, Any]):
    script = _run_script(workflow, "image")
    assert "SM_ENV=production" in script
    assert "SM_CORS_ALLOWED_ORIGINS='*'" in script


def test_actions_are_pinned_to_a_major_version(workflow: dict[str, Any]):
    for job in EXPECTED_JOBS:
        for step in _steps(workflow, job):
            uses = step.get("uses")
            if uses:
                assert "@" in uses, uses
                assert not uses.endswith("@main"), uses
                assert not uses.endswith("@master"), uses


def test_security_job_exists_and_runs_pip_audit(workflow: dict[str, Any]):
    """Phase 17 Unit 3 adds a named `security` job so dependency and container
    scanning have a dedicated gate rather than living buried inside `static`."""
    assert "security" in workflow["jobs"]
    script = _run_script(workflow, "security")
    assert "pip-audit" in script
    assert "--fail-on high critical" in script


def test_security_job_runs_after_static_and_image(workflow: dict[str, Any]):
    needs = workflow["jobs"]["security"].get("needs", [])
    assert "static" in needs
    assert "image" in needs


def test_static_job_runs_pip_audit(workflow: dict[str, Any]):
    script = _run_script(workflow, "static")
    assert "pip-audit" in script
    assert "--fail-on high critical" in script


def test_image_job_scans_the_built_image_with_trivy(workflow: dict[str, Any]):
    steps = _steps(workflow, "image")
    trivy = next(
        (s for s in steps if s.get("uses", "").startswith("aquasecurity/trivy-action")),
        None,
    )
    assert trivy is not None, "the image job has no Trivy container scan"
    assert trivy["with"]["severity"] == "CRITICAL"
    assert trivy["with"]["exit-code"] == 1


def test_unit_job_reports_coverage_without_a_fabricated_threshold(
    workflow: dict[str, Any],
):
    """`--cov` is present (visible coverage); `--cov-fail-under` is absent —
    fabricating a threshold before a real baseline exists violates the
    Engineering Constitution."""
    script = _run_script(workflow, "unit")
    assert "--cov" in script
    assert "--cov-fail-under" not in script


def test_workflow_carries_no_real_secret(workflow: dict[str, Any]):
    """Every credential in the workflow is an obvious CI placeholder, and no
    `secrets.*` expression is needed — no job talks to a third party."""
    rendered = json.dumps(workflow)
    assert "secrets." not in rendered
    for key, value in workflow["env"].items():
        if "PASSWORD" in key or "SECRET" in key or "KEY" in key:
            assert value.startswith("ci-"), f"{key} does not look like a CI placeholder"
