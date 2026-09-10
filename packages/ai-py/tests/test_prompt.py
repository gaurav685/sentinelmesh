from __future__ import annotations

from sm_ai.evidence import EvidenceBuilder
from sm_ai.messages import MessageRole
from sm_ai.prompt import build_grounded_messages


def _bundle() -> object:
    return (
        EvidenceBuilder()
        .add("detection", "det-1", "detection-engine:uuid", "12 failed logins for svc-backup")
        .build()
    )


def test_evidence_never_lands_in_the_system_turn() -> None:
    bundle = _bundle()
    msgs = build_grounded_messages("Summarise this incident.", bundle)  # type: ignore[arg-type]
    assert msgs[0].role is MessageRole.system
    assert "12 failed logins" not in msgs[0].content
    # the evidence text appears only in a user turn
    user_blob = "\n".join(m.content for m in msgs if m.role is MessageRole.user)
    assert "12 failed logins" in user_blob
    assert all(m.role is not MessageRole.system for m in msgs[1:])


def test_system_turn_states_the_untrusted_data_rule_and_no_actions() -> None:
    msgs = build_grounded_messages("x", _bundle())  # type: ignore[arg-type]
    sys = msgs[0].content.lower()
    assert "untrusted_evidence" in sys
    assert "cannot take actions" in sys or "only describe" in sys
    assert "cite an evidence ref" in sys


def test_task_is_its_own_turn_after_the_evidence() -> None:
    msgs = build_grounded_messages("Do the thing.", _bundle())  # type: ignore[arg-type]
    assert msgs[-1].role is MessageRole.user
    assert msgs[-1].content == "Task:\nDo the thing."
