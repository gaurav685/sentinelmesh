"""Cross-tenant isolation (Engineering Constitution §6).

Every route that reads or mutates tenant data is probed from a different
tenant's admin. None of them may reveal or touch the other tenant's rows.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_user_list_contains_only_own_tenant(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    body = client.get("/api/v1/admin/users").json()
    emails = {u["email"] for u in body["items"]}
    tenant_ids = {u["tenant_id"] for u in body["items"]}

    assert fixture.acme_admin.email in emails
    assert fixture.globex_admin.email not in emails
    assert tenant_ids == {str(fixture.acme.id)}


def test_globex_admin_sees_only_globex(client: TestClient, fixture, do_login):
    do_login("globex", fixture.globex_admin.email)
    body = client.get("/api/v1/admin/users").json()
    emails = {u["email"] for u in body["items"]}
    assert emails == {fixture.globex_admin.email}


def test_cannot_grant_a_role_to_a_user_in_another_tenant(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    # A role the target does not already hold, so the assertion below can only
    # fail if this request actually granted it.
    analyst_role = next(x for x in fixture.store.roles.values() if x.name == "analyst")
    assert (fixture.globex_admin.id, analyst_role.id) not in fixture.store.user_roles

    denied = client.post(
        f"/api/v1/admin/users/{fixture.globex_admin.id}/roles",
        json={"role_id": str(analyst_role.id)},
        headers=csrf(r),
    )
    # Indistinguishable from a user that does not exist at all.
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "not_found"
    assert (fixture.globex_admin.id, analyst_role.id) not in fixture.store.user_roles


def test_grant_within_own_tenant_succeeds_and_is_audited(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    analyst_role = next(x for x in fixture.store.roles.values() if x.name == "analyst")

    ok = client.post(
        f"/api/v1/admin/users/{fixture.acme_analyst.id}/roles",
        json={"role_id": str(analyst_role.id)},
        headers=csrf(r),
    )
    assert ok.status_code == 201
    assert ok.json()["name"] == "analyst"
    assert "admin.role.grant" in fixture.audit.actions()
    assert fixture.audit.last()["tenant_id"] == fixture.acme.id


def test_created_user_lands_in_the_callers_tenant_only(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    created = client.post(
        "/api/v1/admin/users",
        json={"email": "fresh@acme-corp.com", "display_name": "Fresh"},
        headers=csrf(r),
    )
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert fixture.store.users[__import__("uuid").UUID(new_id)].tenant_id == fixture.acme.id


def test_me_never_leaks_another_tenant(client: TestClient, fixture, do_login):
    do_login("globex", fixture.globex_admin.email)
    body = client.get("/api/v1/me").json()
    assert body["tenant"]["slug"] == "globex"
    assert body["user"]["tenant_id"] == str(fixture.globex.id)


def test_audit_entries_carry_the_acting_tenant(client: TestClient, fixture, do_login):
    do_login("globex", fixture.globex_admin.email)
    client.get("/api/v1/admin/users")
    tenants = {e["tenant_id"] for e in fixture.audit.entries if e.get("tenant_id")}
    assert fixture.acme.id not in tenants
