#!/usr/bin/env python3
"""Judges: `python3 demo.py` right after cloning — no install, no key, no wallet, no network (recorded real data).
Live public data: `python3 demo.py --live`."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from stockguard.infrastructure.cli import main  # noqa: E402

main(["demo"] + sys.argv[1:])
