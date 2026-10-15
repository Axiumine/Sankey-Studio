"""The message templates of the gate (scripts/githook_messages.py) are all in use."""

from __future__ import annotations

from scripts import githook_messages as msg

from tests.githook_support import REPO_ROOT


def test_every_message_template_is_used_by_a_gate_module() -> None:
    sources = "".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "scripts").glob("githook_*.py")
        if path.name != "githook_messages.py"
    )
    names = [name for name in vars(msg) if name.isupper()]
    assert names
    assert [name for name in names if f"msg.{name}" not in sources] == []
