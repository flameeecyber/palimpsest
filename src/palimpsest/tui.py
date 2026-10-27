"""Terminal UI for Palimpsest.

A curses-based interface over the case store. No external dependencies — just
the standard library. Run with:

    PYTHONPATH=src python -m palimpsest tui --out out

Keys:
  q        quit
  ↑/↓      scroll
  Enter    open selected artifact
  ←/Back   back to dashboard
  v        verify chain of custody
  a        ablation table
  ?        help
"""

from __future__ import annotations

import curses
import locale
from dataclasses import dataclass
from typing import Any

from . import ablate as ablate_mod
from . import manifest as manifest_mod
from .store import Store
from .models import Artifact, Case

# ---- palette ----------------------------------------------------------

_COLOR_BG = 0
_COLOR_TITLE = 1
_COLOR_OK = 2
_COLOR_WARN = 3
_COLOR_BAD = 4
_COLOR_META = 5
_COLOR_HIGHLIGHT = 6
_COLOR_DIM = 7


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_COLOR_TITLE, curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_OK, curses.COLOR_GREEN, -1)
    curses.init_pair(_COLOR_WARN, curses.COLOR_YELLOW, -1)
    curses.init_pair(_COLOR_BAD, curses.COLOR_RED, -1)
    curses.init_pair(_COLOR_META, curses.COLOR_MAGENTA, -1)
    curses.init_pair(_COLOR_HIGHLIGHT, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(_COLOR_DIM, curses.COLOR_BLACK, -1)


# ---- helpers ----------------------------------------------------------


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _center(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    pad = (width - len(text)) // 2
    return " " * pad + text


@dataclass
class ViewState:
    """Shared navigation state between views."""

    out: str = "out"
    selected: int = 0
    scroll: int = 0
    view: str = "dashboard"  # dashboard | artifacts | detail | verify | ablate | help
    artifact: Artifact | None = None
    message: str = ""
    message_type: str = "info"  # info | warn | error | ok


class PalimpsestTUI:
    def __init__(self, stdscr: Any, out: str = "out"):
        self.stdscr = stdscr
        self.state = ViewState(out=out)
        self.store: Store | None = None
        self.case: Case | None = None
        self._load_case()

        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.nodelay(False)
        _init_colors()

    # ---- data ----------------------------------------------------------

    def _load_case(self) -> None:
        try:
            self.store = Store(self.state.out)
            self.store.load()
            self.case = self.store.case
        except FileNotFoundError:
            self.case = None
            self.store = None

    def _artifacts(self) -> list[Artifact]:
        if not self.case:
            return []
        return list(self.case.artifacts)

    def _recovered(self) -> list[Artifact]:
        return [a for a in self._artifacts() if not a.missing]

    def _missing(self) -> list[Artifact]:
        return [a for a in self._artifacts() if a.missing]

    def _stats(self) -> dict[str, Any]:
        if not self.case:
            return {}
        return self.case.stats()

    # ---- drawing primitives --------------------------------------------

    def _clear(self) -> None:
        self.stdscr.erase()

    def _refresh(self) -> None:
        self.stdscr.refresh()

    def _getch(self) -> int:
        return self.stdscr.getch()

    def _draw_border(self, title: str | None = None) -> None:
        height, width = self.stdscr.getmaxyx()
        self.stdscr.attron(curses.color_pair(_COLOR_TITLE))
        self.stdscr.hline(0, 0, curses.ACS_HLINE, width)
        self.stdscr.hline(height - 1, 0, curses.ACS_HLINE, width)
        self.stdscr.vline(0, 0, curses.ACS_VLINE, height)
        self.stdscr.vline(0, width - 1, curses.ACS_VLINE, height)
        self.stdscr.attroff(curses.color_pair(_COLOR_TITLE))
        if title:
            t = _center(title, width - 2)
            self.stdscr.addnstr(1, 1, t, width - 4, curses.color_pair(_COLOR_TITLE))

    def _draw_help_line(self) -> None:
        height, width = self.stdscr.getmaxyx()
        help_text = "q:quit  ↑↓:scroll  Enter:open  ←:back  v:verify  a:ablate  ?:help"
        self.stdscr.addnstr(height - 2, 2, help_text, width - 4, curses.color_pair(_COLOR_DIM))

    def _draw_message(self, y: int, x: int, width: int) -> None:
        if not self.state.message:
            return
        color = {
            "info": _COLOR_META,
            "warn": _COLOR_WARN,
            "error": _COLOR_BAD,
            "ok": _COLOR_OK,
        }.get(self.state.message_type, _COLOR_META)
        self.stdscr.addnstr(y, x, _truncate(self.state.message, width), width, curses.color_pair(color))

    # ---- views ---------------------------------------------------------

    def _view_dashboard(self) -> None:
        self._clear()
        self._draw_border("Palimpsest — case dashboard")
        height, width = self.stdscr.getmaxyx()

        y = 4
        if not self.case:
            self.stdscr.addnstr(y, 4, "No case found. Run `palimpsest run <image> --out out` first.", width - 8)
            self._draw_help_line()
            self._draw_message(height - 4, 4, width - 8)
            self._refresh()
            return

        stats = self._stats()
        recovered = self._recovered()
        missing = self._missing()

        lines = [
            ("Target", self.case.target or "unknown"),
            ("Artifacts", str(len(self._artifacts()))),
            ("Recovered", str(len(recovered))),
            ("Missing / unrecoverable", str(len(missing))),
            ("Clusters", str(len(set(a.cluster_id for a in recovered if a.cluster_id)))),
            ("Narrated", str(stats.get("narrated", 0))),
            ("Grounded sentences", str(stats.get("grounded", 0))),
            ("Struck sentences", str(stats.get("struck", 0))),
            ("Grounded ratio", f"{stats.get('grounded_ratio', 0):.0%}"),
        ]

        for i, (label, value) in enumerate(lines):
            yy = y + i
            self.stdscr.addnstr(yy, 4, label, width - 30, curses.color_pair(_COLOR_META))
            self.stdscr.addnstr(yy, width - len(str(value)) - 4, str(value), width - 8, curses.color_pair(_COLOR_OK))

        y += len(lines) + 2
        self.stdscr.addnstr(y, 4, "Clusters:", width - 8, curses.color_pair(_COLOR_TITLE))
        y += 1
        clusters: dict[str, list[Artifact]] = {}
        for a in recovered:
            clusters.setdefault(a.cluster_id or "unlinked", []).append(a)
        for cid, members in clusters.items():
            yy = y
            self.stdscr.addnstr(yy, 6, f"{cid} ({len(members)} files)", width - 12)
            y += 1

        self._draw_help_line()
        self._draw_message(height - 4, 4, width - 8)
        self._refresh()

    def _view_artifacts(self) -> None:
        self._clear()
        self._draw_border("Artifacts (↑↓ scroll, Enter open)")
        height, width = self.stdscr.getmaxyx()

        artifacts = self._artifacts()
        if not artifacts:
            self.stdscr.addnstr(4, 4, "No artifacts in case.", width - 8)
            self._draw_help_line()
            self._refresh()
            return

        # clamp selection
        if self.state.selected >= len(artifacts):
            self.state.selected = len(artifacts) - 1
        if self.state.selected < 0:
            self.state.selected = 0

        # visible window
        view_h = height - 8
        if self.state.scroll > self.state.selected:
            self.state.scroll = self.state.selected
        if self.state.scroll < self.state.selected - view_h + 1:
            self.state.scroll = self.state.selected - view_h + 1
        if self.state.scroll < 0:
            self.state.scroll = 0

        header = f"{'#':<4} {'id':<10} {'name':<34} {'kind':<10} {'status':<14} {'size':>8}"
        self.stdscr.addnstr(3, 4, header, width - 8, curses.color_pair(_COLOR_TITLE))

        y = 4
        end = min(self.state.scroll + view_h, len(artifacts))
        for idx in range(self.state.scroll, end):
            a = artifacts[idx]
            status = "MISSING" if a.missing else "recovered"
            status_color = _COLOR_BAD if a.missing else _COLOR_OK
            row = f"{idx:<4} {a.id:<10} {_truncate(a.original_name or a.id, 34):<34} {a.kind:<10} {status:<14} {a.size:>8}"
            if idx == self.state.selected:
                self.stdscr.addnstr(y, 4, row, width - 8, curses.color_pair(_COLOR_HIGHLIGHT) | curses.A_BOLD)
            else:
                attr = curses.color_pair(status_color) if a.missing else 0
                self.stdscr.addnstr(y, 4, row, width - 8, attr)
            y += 1

        if len(artifacts) > view_h:
            self.stdscr.addnstr(height - 4, 4, f"showing {self.state.scroll + 1}-{end} of {len(artifacts)}", width - 8, curses.color_pair(_COLOR_DIM))

        self._draw_help_line()
        self._draw_message(height - 3, 4, width - 8)
        self._refresh()

    def _view_detail(self) -> None:
        self._clear()
        a = self.state.artifact
        if not a:
            self.state.view = "artifacts"
            return

        self._draw_border(f"Artifact: {a.original_name or a.id}")
        height, width = self.stdscr.getmaxyx()

        y = 4
        fields = [
            ("ID", a.id),
            ("Original name", a.original_name or "—"),
            ("Kind", a.kind),
            ("Size", f"{a.size} bytes"),
            ("Status", "missing / unrecoverable" if a.missing else "recovered"),
            ("Created", a.created_at or "—"),
            ("Deleted", a.deleted_at or "—"),
            ("Cluster", a.cluster_id or "none"),
            ("Narrated by", a.narration_model or "—"),
        ]
        for label, value in fields:
            self.stdscr.addnstr(y, 4, label, 20, curses.color_pair(_COLOR_META))
            self.stdscr.addnstr(y, 24, _truncate(str(value), width - 28), width - 28)
            y += 1

        y += 1
        # Epitaph
        epitaph = a.epitaph
        self.stdscr.addnstr(y, 4, "Epitaph:", width - 8, curses.color_pair(_COLOR_TITLE))
        y += 1
        if epitaph:
            self.stdscr.addnstr(y, 6, _truncate(epitaph, width - 10), width - 10, curses.A_BOLD)
        else:
            self.stdscr.addnstr(y, 6, "(no epitaph)", width - 10, curses.color_pair(_COLOR_DIM))
        y += 2

        # Claims with evidence
        self.stdscr.addnstr(y, 4, "Claims:", width - 8, curses.color_pair(_COLOR_TITLE))
        y += 1
        if not a.claims:
            self.stdscr.addnstr(y, 6, "(no claims)", width - 10, curses.color_pair(_COLOR_DIM))
            y += 1
        else:
            for c in a.claims:
                mark = "✓" if not c.struck else "✗"
                mark_color = _COLOR_OK if not c.struck else _COLOR_BAD
                line = f"  {mark} {_truncate(c.text, width - 12)}"
                self.stdscr.addnstr(y, 6, line, width - 10, curses.color_pair(mark_color))
                y += 1
                ev = ", ".join(c.evidence) if c.evidence else "no citation"
                self.stdscr.addnstr(y, 8, f"    evidence: {ev}  support: {c.support:.2f}", width - 12, curses.color_pair(_COLOR_DIM))
                if c.struck and c.reason:
                    self.stdscr.addnstr(y + 1, 8, f"    struck: {c.reason}", width - 12, curses.color_pair(_COLOR_BAD))
                    y += 1
                y += 1

        y += 1
        # Evidence table
        self.stdscr.addnstr(y, 4, "Evidence:", width - 8, curses.color_pair(_COLOR_TITLE))
        y += 1
        if not a.evidence:
            self.stdscr.addnstr(y, 6, "(no evidence)", width - 10, curses.color_pair(_COLOR_DIM))
        else:
            for e in a.evidence:
                line = f"  [{e.id}] {e.source}: {_truncate(e.value, width - 16)}"
                self.stdscr.addnstr(y, 6, line, width - 10, 0)
                y += 1

        self._draw_help_line()
        self._refresh()

    def _view_verify(self) -> None:
        self._clear()
        self._draw_border("Verify — chain of custody")
        height, width = self.stdscr.getmaxyx()

        if not self.store:
            self.stdscr.addnstr(4, 4, "No case store available.", width - 8)
            self._draw_help_line()
            self._refresh()
            return

        import subprocess
        import sys

        try:
            result = subprocess.run(
                [sys.executable, "-m", "palimpsest", "verify", "--out", self.state.out],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout.splitlines()
        except Exception as exc:
            output = [f"verify failed: {exc}"]

        y = 4
        for line in output:
            if y >= height - 3:
                break
            color = _COLOR_OK if line.startswith("ok") else (_COLOR_BAD if "failed" in line.lower() else 0)
            self.stdscr.addnstr(y, 4, _truncate(line, width - 8), width - 8, curses.color_pair(color))
            y += 1

        self._draw_help_line()
        self._refresh()

    def _view_ablate(self) -> None:
        self._clear()
        self._draw_border("Ablation — model vs baseline")
        height, width = self.stdscr.getmaxyx()

        if not self.store:
            self.stdscr.addnstr(4, 4, "No case store available.", width - 8)
            self._draw_help_line()
            self._refresh()
            return

        try:
            result = ablate_mod.compare(self.state.out)
            table = ablate_mod.format_table(result)
        except Exception as exc:
            table = f"ablate failed: {exc}"

        y = 4
        for line in table.splitlines():
            if y >= height - 3:
                break
            self.stdscr.addnstr(y, 4, _truncate(line, width - 8), width - 8)
            y += 1

        self._draw_help_line()
        self._refresh()

    def _view_help(self) -> None:
        self._clear()
        self._draw_border("Help")
        height, width = self.stdscr.getmaxyx()

        help_text = [
            "Palimpsest Terminal UI",
            "",
            "Navigation:",
            "  ↑ / ↓   scroll through artifact list",
            "  Enter   open selected artifact detail",
            "  ← / Backspace  return to dashboard",
            "  q       quit",
            "",
            "Actions:",
            "  v       run verify (chain of custody)",
            "  a       show ablation table (model vs baseline)",
            "  ?       show this help",
            "",
            "Views:",
            "  dashboard  case summary and clusters",
            "  artifacts  scrollable list of all artifacts",
            "  detail     epitaph, claims, evidence for one artifact",
            "  verify     check hashes, citations, support, drift",
            "  ablate     what the model adds over the stat baseline",
            "",
            "Palimpsest recovers deleted files from a disk image and",
            "explains what they were using local open-weight models.",
        ]

        y = 4
        for line in help_text:
            if y >= height - 3:
                break
            self.stdscr.addnstr(y, 4, _truncate(line, width - 8), width - 8)
            y += 1

        self._draw_help_line()
        self._refresh()

    # ---- main loop -----------------------------------------------------

    def run(self) -> int:
        while True:
            view = self.state.view
            if view == "dashboard":
                self._view_dashboard()
            elif view == "artifacts":
                self._view_artifacts()
            elif view == "detail":
                self._view_detail()
            elif view == "verify":
                self._view_verify()
            elif view == "ablate":
                self._view_ablate()
            elif view == "help":
                self._view_help()
            else:
                self.state.view = "dashboard"

            key = self._getch()

            if key in (ord("q"), ord("Q")):
                return 0

            if view == "detail":
                if key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 263):
                    self.state.view = "artifacts"
                    self.state.artifact = None
                continue

            if view in ("verify", "ablate", "help"):
                if key in (ord("q"), ord("Q"), curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 263):
                    self.state.view = "dashboard"
                continue

            # dashboard / artifacts navigation
            artifacts = self._artifacts()
            if key in (curses.KEY_UP,) and artifacts:
                self.state.selected = max(0, self.state.selected - 1)
            elif key in (curses.KEY_DOWN,) and artifacts:
                self.state.selected = min(len(artifacts) - 1, self.state.selected + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                if view == "dashboard":
                    self.state.view = "artifacts"
                    self.state.selected = 0
                    self.state.scroll = 0
                elif view == "artifacts" and artifacts:
                    self.state.artifact = artifacts[self.state.selected]
                    self.state.view = "detail"
            elif key in (ord("v"), ord("V")):
                self.state.view = "verify"
            elif key in (ord("a"), ord("A")):
                self.state.view = "ablate"
            elif key in (ord("?"), ord("/")):
                self.state.view = "help"
            elif key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 263):
                if view == "artifacts":
                    self.state.view = "dashboard"


def tui_main(out: str = "out") -> int:
    return curses.wrapper(PalimpsestTUI, out).run()
