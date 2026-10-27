"""Prompts are plain text files on disk, not strings buried in code.

That is a feature, not a style choice: the behaviour of the agent is something
a user can read, diff, and change without touching Python. It is also the part
of this project that a closed model would not let you do at all.
"""

from __future__ import annotations

import os
from pathlib import Path

PROMPT_DIR = Path(
    os.environ.get(
        "PALIMPSEST_PROMPTS",
        Path(__file__).resolve().parents[2] / "prompts",
    )
)


def load(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def render(name: str, **values: object) -> str:
    text = load(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
