"""Drive the real editor window against a headless app (skipped without a display)."""

import json

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def _app(tmp_path):
    from tests.test_app import _headless

    return _headless(tmp_path)


def test_edit_steps_and_rules_then_save_as_new_applies(root, tmp_path, monkeypatch):
    from src.runtime.protocol_editor_gui import ProtocolEditor

    app = _app(tmp_path)
    ed = ProtocolEditor(root, app)
    assert len(ed.tree.get_children()) == 4  # open, handle_a, handle_b, close (groups hold the rest)

    # edit a step's prompt through the form
    ed.tree.selection_set("remove_a"); ed._load_form()
    ed.f["prompt"].set("Take out the first module.")
    ed.update_row()
    assert ed._row("remove_a").prompt == "Take out the first module."

    # rename a step: references follow
    ed.tree.selection_set("stow_a_lid"); ed._load_form()
    ed.f["id"].set("park_a_lid"); ed.update_row()
    assert "park_a_lid" in ed._row("close_a_lid").after

    # a rule: longer attendance grace
    ed.rtree.selection_set("attended_while_open"); ed._load_rule()
    ed.r_timer.set("9"); ed.apply_rule()
    assert ed._rules["attended_while_open"].timer == 9.0

    # a locked rule stays on even if the box is unticked
    ed.rtree.selection_set("no_loose_objects"); ed._load_rule()
    assert str(ed.on_chk.cget("state")) == "disabled"

    ed.pid_var.set("my_variant")
    out = tmp_path / "my_variant.json"
    ed._write_and_apply(out)
    assert out.exists() and app.protocol_path == out
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["protocol_id"] == "my_variant"
    grace = {c.id: c for c in app.resolved.constraints}["attended_while_open"].params["grace_s"]
    assert grace == 9.0
    assert "park_a_lid" in [s["id"] for s in app.status().protocol["steps"]]
    ed.dirty = False
    ed.close()


def test_invalid_experiment_is_not_saved(root, tmp_path):
    from src.runtime.protocol_editor_gui import ProtocolEditor

    app = _app(tmp_path)
    ed = ProtocolEditor(root, app)
    ed.tree.selection_set("close_container"); ed._load_form()
    ed.f["after"].set("handle_a, does_not_exist"); ed.update_row()
    assert ed.validate() is False
    out = tmp_path / "broken.json"
    ed._write_and_apply(out)
    assert not out.exists() and app.protocol_path != out
    assert "does_not_exist" in ed.msg.get("1.0", "end")
    ed.dirty = False
    ed.close()


def test_add_group_and_step(root, tmp_path):
    from src.runtime.protocol_editor_gui import ProtocolEditor

    ed = ProtocolEditor(root, _app(tmp_path))
    n = len(ed.rows)
    ed.tree.selection_set("open_container"); ed.add_row("step")
    ed.add_row("group")
    assert len(ed.rows) == n + 3  # step + group + the group's first step
    raw = ed.current_raw()
    assert any(s.get("type") == "group" and s["id"].startswith("new_group") for s in raw["steps"])
    ed.dirty = False
    ed.close()


def test_reference_protocol_cannot_be_overwritten_from_the_editor(root, tmp_path):
    from src.runtime.protocol_editor_gui import REFERENCE_PROTOCOLS, ProtocolEditor

    app = _app(tmp_path)
    ed = ProtocolEditor(root, app)
    assert ed.path.name in REFERENCE_PROTOCOLS
    copy = tmp_path / ed.path.name  # same name, so a regression cannot touch the real file
    copy.write_bytes(ed.path.read_bytes())
    ed.path = copy
    before = copy.read_bytes()
    ed.tree.selection_set("remove_a"); ed._load_form()
    ed.f["prompt"].set("Changed."); ed.update_row()
    ed.save_apply()
    assert ed.path.read_bytes() == before
    assert "Save as new" in ed.msg.get("1.0", "end")
    ed.dirty = False
    ed.close()


def test_save_refuses_while_the_form_has_unapplied_changes(root, tmp_path):
    from src.runtime.protocol_editor_gui import ProtocolEditor

    ed = ProtocolEditor(root, _app(tmp_path))
    ed.tree.selection_set("remove_a"); ed._load_form()
    assert ed.unapplied_step() is None
    ed.f["prompt"].set("Take out the first module.")  # typed, not applied
    assert ed.unapplied_step() == "remove_a"
    out = tmp_path / "unapplied.json"
    ed._write_and_apply(out)
    assert not out.exists() and "not applied" in ed.msg.get("1.0", "end")
    ed.update_row()
    assert ed.unapplied_step() is None
    ed.f["action"].set("dwell")
    assert "operator confirms" in ed.action_help.cget("text")
    ed.dirty = False
    ed.close()


def test_time_limit_and_out_together_through_the_form(root, tmp_path):
    from src.runtime.protocol_editor_gui import ProtocolEditor

    app = _app(tmp_path)
    ed = ProtocolEditor(root, app)

    ed.tree.selection_set("remove_b"); ed._load_form()
    ed.f["time_limit"].set("0"); ed.update_row()
    assert ed._row("remove_b").time_limit is None  # refused, not applied
    ed.f["time_limit"].set("45"); ed.update_row()
    assert ed._row("remove_b").time_limit == 45.0
    assert ed.tree.set("remove_b", "limit") == "45"

    ed.tree.selection_set("handle_b"); ed._load_form()
    assert ed.f["together"].get() == "forbidden"
    ed.f["together"].set("permitted"); ed.update_row()
    assert ed.unapplied_step() is None

    # the step_time_limit rule is listed, with no rule-level timer
    rule = ed._rules["step_time_limit"]
    assert rule.enabled and rule.timer_key is None

    ed.pid_var.set("timed_variant")
    out = tmp_path / "timed_variant.json"
    ed._write_and_apply(out)
    assert out.exists() and app.protocol_path == out
    saved = json.loads(out.read_text(encoding="utf-8"))
    handle_b = next(n for n in saved["steps"] if n["id"] == "handle_b")
    assert handle_b["concurrency"] == "permitted"
    assert next(s for s in handle_b["steps"] if s["id"] == "remove_b")["timeout_s"] == 45.0
    ed.dirty = False
    ed.close()
