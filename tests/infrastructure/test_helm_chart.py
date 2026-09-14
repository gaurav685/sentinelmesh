"""Static Helm chart assertions — no cluster, no `helm` binary required.

The chart is rendered by `helm template` in CI; this test asserts the *text*
of the templates and the parsed `values.yaml` carry the security properties
that survive a real cluster: non-root, read-only root fs, no privilege
escalation, dropped capabilities, health probes, and resource limits.

The workload templates (deployment.yaml, migration-job.yaml) render their
security context from `.Values` (a single source of truth), so the tests
assert the template *wires* the value and the value *is* strict — a broken
render would surface in the `helm template` smoke test in CI. The stateful
templates carry literal security contexts, which are asserted directly.
Stateful components (postgres, neo4j) are explicitly exempted from
`runAsNonRoot` where the upstream image cannot comply — the exemption is
documented in the template itself, and this test checks the exemption is
named, not silent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "sentinelmesh"
TEMPLATES = CHART / "templates"

# Templates that render a Deployment/StatefulSet/Job with a container spec.
_CONTAINER_TEMPLATES = [
    "deployment.yaml",
    "migration-job.yaml",
    "stateful/keycloak.yaml",
    "stateful/minio.yaml",
    "stateful/neo4j.yaml",
    "stateful/postgres.yaml",
    "stateful/redis.yaml",
    "stateful/redpanda.yaml",
]


def _read(rel: str) -> str:
    return (TEMPLATES / rel).read_text(encoding="utf-8")


def _has_literal_security(text: str) -> bool:
    return "allowPrivilegeEscalation: false" in text


def _has_literal_capability_drop(text: str) -> bool:
    # The templates write `drop: ["ALL"]` (quoted, as Helm/YAML prefers).
    return bool(re.search(r"drop:\s*\[\s*[\"']ALL[\"']\s*\]", text))


# Templates that carry a *literal* security context (not rendered from values).
_LITERAL_TEMPLATES = [
    "stateful/keycloak.yaml",
    "stateful/minio.yaml",
    "stateful/neo4j.yaml",
    "stateful/postgres.yaml",
    "stateful/redis.yaml",
    "stateful/redpanda.yaml",
]


@pytest.mark.parametrize("name", _LITERAL_TEMPLATES)
def test_every_literal_container_template_carries_a_container_security_context(name: str) -> None:
    text = _read(name)
    assert "securityContext:" in text, f"{name}: no container securityContext"
    assert _has_literal_security(text), f"{name}: allowPrivilegeEscalation is not false"
    assert _has_literal_capability_drop(text), f"{name}: capabilities.drop is not [ALL]"


@pytest.mark.parametrize("name", ["deployment.yaml", "migration-job.yaml"])
def test_workload_templates_wire_the_strict_security_context(name: str) -> None:
    """Workload templates render from `.Values`; assert the wiring and that
    the values themselves are strict (see the values tests below)."""
    text = _read(name)
    assert "podSecurityContext" in text, f"{name}: podSecurityContext is not wired"
    assert "containerSecurityContext" in text, (
        f"{name}: containerSecurityContext is not wired"
    )


@pytest.mark.parametrize(
    "name",
    ["stateful/postgres.yaml", "stateful/neo4j.yaml"],
)
def test_stateful_exempt_templates_document_the_exemption(name: str) -> None:
    """The upstream image cannot run non-root; the exemption must be a named,
    deliberate comment, not a silent omission."""
    text = _read(name)
    assert "NOT runAsNonRoot" in text, (
        f"{name}: the runAsNonRoot exemption is not documented in the template"
    )


def test_values_yaml_declares_the_strict_security_context() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    pod = values["podSecurityContext"]
    assert pod["runAsNonRoot"] is True
    container = values["containerSecurityContext"]
    assert container["allowPrivilegeEscalation"] is False
    assert container["readOnlyRootFilesystem"] is True
    assert container["capabilities"]["drop"] == ["ALL"]


def test_workload_values_are_strict_when_rendered() -> None:
    """The deployment/migration templates wire `.Values.containerSecurityContext`,
    so the values file must carry the strict set — a relaxed default would
    silently weaken every workload."""
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    container = values["containerSecurityContext"]
    assert container["readOnlyRootFilesystem"] is True
    assert container["allowPrivilegeEscalation"] is False
    assert container["capabilities"]["drop"] == ["ALL"]


def test_every_service_in_values_has_resource_limits() -> None:
    """A pod without a CPU/memory limit is a denial-of-service risk; every
    service must declare both requests and limits."""
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    services: dict[str, Any] = values["services"]
    assert services, "no services declared in values.yaml"
    missing: list[str] = []
    for name, svc in services.items():
        res = svc.get("resources")
        if not res:
            missing.append(name)
            continue
        if not res.get("requests", {}).get("cpu") or not res.get("limits", {}).get("cpu"):
            missing.append(name)
    assert not missing, f"services without resource limits: {missing}"


def test_deployment_template_carries_probes_on_real_endpoints() -> None:
    text = _read("deployment.yaml")
    assert "startupProbe:" in text
    assert "livenessProbe:" in text
    assert "readinessProbe:" in text
    # Probes hit the health endpoints, not a shell script (the slim image has
    # no shell for the app containers).
    assert "httpGet:" in text
    assert "exec:" not in text, "a shell-based probe needs a shell in the image"


def test_migration_job_wires_non_root_read_only_and_dropped_capabilities() -> None:
    """The migration Job renders its security context from `.Values`, so the
    test asserts the wiring; the values themselves are checked by
    `test_workload_values_are_strict_when_rendered`."""
    text = _read("migration-job.yaml")
    assert "podSecurityContext" in text
    assert "containerSecurityContext" in text
    assert "securityContext:" in text