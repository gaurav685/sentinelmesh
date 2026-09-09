from __future__ import annotations

from sm_ti_service.publish import PLATFORM_TENANT, ti_update_envelope

from sm_contracts import EventType, TiUpdateAction

from .conftest import indicator


def test_global_indicator_uses_the_platform_tenant_on_the_envelope() -> None:
    env = ti_update_envelope(indicator(), TiUpdateAction.added)
    assert env.event_type is EventType.ti_indicator_updated
    assert env.tenant_id == PLATFORM_TENANT
    assert env.payload.tenant_id is None  # scope is the payload's, and it is global
    assert env.partition_key == "fixture:demo"
    assert env.payload.action is TiUpdateAction.added
    assert env.event_id == env.payload.indicator_id


def test_envelope_round_trips() -> None:
    from sm_contracts import EventEnvelope, TiUpdatePayload

    env = ti_update_envelope(indicator(), TiUpdateAction.expired)
    back = EventEnvelope[TiUpdatePayload].model_validate_json(env.model_dump_json())
    assert back.payload.action is TiUpdateAction.expired
