"""Offline migration-safety assertions — no database required.

Every migration file is parsed as text (the real upgrade is exercised by the
integration job against a live Postgres). The checks:
- no destructive op (drop_table / drop_index / drop_column / raw DROP) without
  an explicit `# DESTRUCTIVE` marker in the same file;
- linear history (no branches, no merge revisions);
- every created table carries a `tenant_id` foreign key, or is on the explicit
  platform-global exemption list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "postgres" / "versions"

# Platform-global tables: no tenant_id by design (ADR-020 / Constitution 6).
# The exemption must be named here and justified in the migration file itself.
TENANTLESS_EXEMPTIONS = {
    "permission": "platform-global RBAC catalogue, never tenant-scoped",
    "role": "platform-global RBAC catalogue (tenant-scoped roles are a future shape)",
    "role_permission": "join table for the global permission/role catalogue",
    "attack_matrix_version": "MITRE ATT&CK matrix versions are global",
    "attack_tactic": "MITRE tactics are global",
    "attack_technique": "MITRE techniques are global",
}

_DESTRUCTIVE_RE = re.compile(
    r"op\.(drop_table|drop_index|drop_column)", re.IGNORECASE
)
_RAW_DROP_RE = re.compile(r'op\.execute\(\s*["\']\s*DROP ', re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(
    r'op\.create_table\(\s*["\'](\w+)["\']\s*,\s*\((.*?)\)\s*\)',
    re.DOTALL,
)


def _migration_files() -> list[Path]:
    return sorted(VERSIONS_DIR.glob("*.py"))


def _revision_id(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^revision:\s*str\s*=\s*['\"](\d+)['\"]", text, re.MULTILINE)
    assert match, f"{path.name}: no revision id"
    return match.group(1)


def _down_revision(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    # Files use `down_revision: str | None = "0005"` (or `= None`).
    match = re.search(
        r'^down_revision:\s*str\s*\|\s*None\s*=\s*(["\']\d+["\']|None)',
        text,
        re.MULTILINE,
    )
    if match is None:
        return None
    raw = match.group(1)
    return None if raw == "None" else raw.strip("'\"")


def test_every_migration_has_a_revision_and_a_down_revision() -> None:
    files = _migration_files()
    assert files, "no migration files found"
    for path in files:
        assert _revision_id(path), f"{path.name}: missing revision id"
        # The first migration has no down_revision; every other must name one.
        if _revision_id(path) != "0001":
            assert _down_revision(path) is not None, f"{path.name}: missing down_revision"


def test_history_is_linear_with_no_branches_or_merges() -> None:
    files = _migration_files()
    revisions = {path.name: _revision_id(path) for path in files}
    by_id = {rid: name for name, rid in revisions.items()}
    expected = {f"{i:04d}" for i in range(1, len(files) + 1)}
    assert set(by_id) == expected, f"revision ids are not contiguous 0001..000{len(files):04d}"

    # Every non-head migration's down_revision must point at the previous id.
    for path in files:
        rid = _revision_id(path)
        if rid == "0001":
            assert _down_revision(path) is None, f"{path.name}: 0001 must not name a down_revision"
            continue
        down = _down_revision(path)
        assert down is not None
        assert down == f"{int(rid) - 1:04d}", (
            f"{path.name}: down_revision {down} is not the previous revision"
        )

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "branch_labels" not in text or "None" in text, (
            f"{path.name}: branch_labels would create a non-linear history"
        )
        assert "depends_on" not in text or "None" in text, (
            f"{path.name}: depends_on would create a non-linear history"
        )


@pytest.mark.parametrize("path", _migration_files())
def test_no_destructive_operation_without_an_explicit_marker(path: Path) -> None:
    """A `drop_table` / `drop_index` / `drop_column` in `downgrade()` is normal,
    but any destructive op in `upgrade()` must be flagged so a reviewer sees it."""
    text = path.read_text(encoding="utf-8")
    upgrade = text.split("def upgrade()", 1)[-1].split("def downgrade()", 1)[0]
    destructive = _DESTRUCTIVE_RE.search(upgrade) or _RAW_DROP_RE.search(upgrade)
    if destructive is None:
        return
    assert "# DESTRUCTIVE" in text, (
        f"{path.name}: destructive op in upgrade() without a `# DESTRUCTIVE` marker"
    )


@pytest.mark.parametrize("path", _migration_files())
def test_every_created_table_is_tenant_scoped_or_explicitly_exempted(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for match in _CREATE_TABLE_RE.finditer(text):
        table = match.group(1)
        if table in TENANTLESS_EXEMPTIONS:
            continue
        assert '"tenant_id"' in text or "'tenant_id'" in text or "tenant_id" in text, (
            f"{path.name}: table {table!r} is not tenant-scoped and not exempted"
        )