#!/usr/bin/env python3
"""Hermes entrypoint for the weekday Daily Financial Briefing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import main_for  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main_for("weekday"))
