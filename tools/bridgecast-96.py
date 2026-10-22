#!/usr/bin/env python3
"""Compatibility launcher for BridgeMix's PipeWire audio-profile manager."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if SOURCE_ROOT.is_dir():
    sys.path.insert(0, str(SOURCE_ROOT))

from bridgemix.audio_profile import main


if __name__ == "__main__":
    raise SystemExit(main())
