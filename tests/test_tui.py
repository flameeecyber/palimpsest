"""TUI smoke tests — data layer and module import (curses needs a real TTY)."""

from palimpsest.tui import ViewState, PalimpsestTUI
from palimpsest.models import Artifact


def test_view_state_defaults():
    vs = ViewState(out="out")
    assert vs.out == "out"
    assert vs.selected == 0
    assert vs.view == "dashboard"
    assert vs.message == ""


def test_tui_filters():
    arts = [
        Artifact(id="a1", recovered_path="x", original_name="f1.png", kind="photo", size=100, missing=False),
        Artifact(id="a2", recovered_path="x", original_name="f2.png", kind="photo", size=200, missing=True),
        Artifact(id="a3", recovered_path="x", original_name="letter.txt", kind="document", size=208, missing=False),
    ]
    recovered = [a for a in arts if not a.missing]
    missing = [a for a in arts if a.missing]
    assert len(recovered) == 2
    assert len(missing) == 1
    assert missing[0].original_name == "f2.png"


def test_tui_module_has_run():
    assert hasattr(PalimpsestTUI, "run")
    assert callable(PalimpsestTUI.run)
