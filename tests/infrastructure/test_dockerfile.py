"""Static Dockerfile analysis — no Docker required.

The real image build is verified by the CI `image` job; this test asserts the
*text* of the Dockerfile carries the properties that survive a `docker run`
standalone (no Kubernetes liveness probes): a non-root UID, no secrets, no
undeclared exposed ports, a health check, no `:latest` tags, and no
`curl | bash` supply-chain pattern.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "Dockerfile.app"

# A port declared in EXPOSE that is not 8000 would be a smell — the image serves
# one API on one port; everything else comes from the compose / Helm layer.
_DECLARED_PORTS = {"8000"}


def _read() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_dockerfile_exists() -> None:
    assert DOCKERFILE.is_file(), "Dockerfile.app must exist for the image job"


def test_runtime_user_is_non_root() -> None:
    """The runtime stage must run as a non-root UID (the CI image job asserts
    the actual uid is 10001; this test asserts the *instruction* is present)."""
    text = _read()
    assert re.search(r"^\s*USER\s+\d+", text, re.MULTILINE), "no USER instruction"
    match = re.search(r"^\s*USER\s+(\d+)", text, re.MULTILINE)
    assert match is not None
    assert int(match.group(1)) != 0, "the image runs as root"


def test_no_secret_is_baked_into_the_image() -> None:
    """The Dockerfile must not copy `.env`, credentials, or keys into the image.
    Secrets arrive at runtime via the environment or a mounted secret."""
    text = _read()
    for bad in (".env", "id_rsa", "credentials", "secrets/"):
        assert bad not in text, f"the Dockerfile references {bad!r}"


def test_only_declared_ports_are_exposed() -> None:
    text = _read()
    ports = re.findall(r"^\s*EXPOSE\s+(\d+)", text, re.MULTILINE)
    assert ports, "no EXPOSE instruction"
    assert set(ports) <= _DECLARED_PORTS, f"undeclared ports: {set(ports) - _DECLARED_PORTS}"


def test_healthcheck_is_present() -> None:
    """A standalone `docker run` needs its own liveness signal; Kubernetes
    probes are a deployment-layer concern, not an image property."""
    text = _read()
    match = re.search(r"^\s*HEALTHCHECK\s.*?CMD\s+(.+)$", text, re.MULTILINE | re.DOTALL)
    assert match, "no HEALTHCHECK"
    # The check must not depend on a tool the slim image does not ship.
    assert "curl" not in match.group(1), "HEALTHCHECK uses curl, which the slim image lacks"
    assert "wget" not in match.group(1), "HEALTHCHECK uses wget, which the slim image lacks"


def test_no_latest_tags_are_used() -> None:
    """Tag-mutable base images are a supply-chain risk; every FROM must pin a
    digest or at least a non-`latest` tag."""
    text = _read()
    for line in text.splitlines():
        if line.strip().startswith("FROM "):
            assert ":latest" not in line, f"mutable tag in: {line}"


def test_no_curl_pipe_bash_supply_chain_pattern() -> None:
    """No `curl ... | bash` download-and-execute in the build or runtime."""
    text = _read()
    assert not re.search(r"curl[^\n]*\|\s*(?:ba)?sh", text), "curl|bash pattern present"
    assert not re.search(r"wget[^\n]*\|\s*(?:ba)?sh", text), "wget|bash pattern present"


def test_runtime_stage_copies_only_the_venv_and_artifacts() -> None:
    """The runtime stage must not carry a compiler or build cache."""
    text = _read()
    runtime = text.split("FROM python:3.11-slim-bookworm AS runtime", 1)[-1]
    assert "build-essential" not in runtime, "compiler ships in the runtime image"
    assert "apt-get" not in runtime, "package manager runs in the runtime image"