#!/usr/bin/env python3
"""Seed the isolated SentinelMesh demo tenant (Phase 18 — Demo Mode).

    python scripts/seed_demo.py

Creates (idempotent — safe to re-run):

  - a tenant named/labelled as demo/synthetic (never "default", never a name
    that could be mistaken for a real customer)
  - one demo admin user with a real Argon2id password hash, so the local
    email/password login path works out of the box
  - the `tenant_admin` system role granted to that user (self-granted, since
    a brand-new tenant has no other user to grant it)

This does NOT generate synthetic telemetry/detections/attack chains --
that is `simulation-service`'s job (APT / ransomware / insider / brute-force
scenarios), run from the SOC UI's Simulation tab, or via
`POST /api/v1/simulation/scenarios/{scenario_id}/run` once logged in. Every
event that path produces is already labelled `simulated` end-to-end
(ADR from Phase 12) -- this script only provisions the account used to
log in and trigger it.

Target Postgres comes from the validated `AppSettings` (`SM_PG_*`), same as
the service -- no connection string on the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from sm_common.config import AppSettings
from sm_common.db.models import Role, Tenant, User, UserRole
from sm_common.db.session import Database
from sm_common.security.passwords import hash_password

DEMO_TENANT_SLUG = "demo-corp"
DEMO_TENANT_NAME = "SentinelMesh Demo Corp (SYNTHETIC DATA ONLY -- not a real organization)"
DEMO_ADMIN_EMAIL = "demo-admin@sentinelmesh.demo"
DEMO_ADMIN_DISPLAY_NAME = "Demo Admin"
DEMO_ADMIN_ROLE = "tenant_admin"


def _settings() -> AppSettings:
    return AppSettings(service_name="seed-demo")  # SM_PG_* from the env


async def _run(password: str) -> int:
    db = Database.from_settings(_settings())
    async with db.session() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
        if tenant is None:
            tenant = Tenant(slug=DEMO_TENANT_SLUG, name=DEMO_TENANT_NAME, status="active")
            session.add(tenant)
            await session.flush()
            print(f"created tenant: {DEMO_TENANT_SLUG}")
        else:
            print(f"tenant already exists: {DEMO_TENANT_SLUG}")

        user = await session.scalar(
            select(User).where(User.tenant_id == tenant.id, User.email == DEMO_ADMIN_EMAIL)
        )
        if user is None:
            user = User(
                tenant_id=tenant.id,
                email=DEMO_ADMIN_EMAIL,
                display_name=DEMO_ADMIN_DISPLAY_NAME,
                status="active",
                password_hash=hash_password(password),
            )
            session.add(user)
            await session.flush()
            print(f"created user: {DEMO_ADMIN_EMAIL}")
        else:
            user.password_hash = hash_password(password)
            print(f"user already exists, password reset: {DEMO_ADMIN_EMAIL}")

        role = await session.scalar(
            select(Role).where(Role.name == DEMO_ADMIN_ROLE, Role.tenant_id.is_(None))
        )
        if role is None:
            print(f"FATAL: system role '{DEMO_ADMIN_ROLE}' not found -- run migrations first")
            return 1

        existing_grant = await session.scalar(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
        )
        if existing_grant is None:
            # Bootstrap: a brand-new tenant has no other user to grant this, so
            # the demo admin's own role grant is self-attributed.
            session.add(UserRole(user_id=user.id, role_id=role.id, granted_by=user.id))
            print(f"granted role: {DEMO_ADMIN_ROLE}")
        else:
            print(f"role already granted: {DEMO_ADMIN_ROLE}")

        await session.commit()

    print()
    print("Demo login (SYNTHETIC tenant, not a real customer):")
    print(f"  tenant:   {DEMO_TENANT_SLUG}")
    print(f"  email:    {DEMO_ADMIN_EMAIL}")
    print(f"  password: {password}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--password",
        default="demo-password-change-me",
        help="Password for the demo admin (default: a clearly-labelled placeholder, dev/demo only)",
    )
    args = ap.parse_args()
    sys.exit(asyncio.run(_run(args.password)))


if __name__ == "__main__":
    main()
