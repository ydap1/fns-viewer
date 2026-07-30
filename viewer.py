#!/usr/bin/env python3
"""Launch the viewer: `python3 viewer.py --open-browser`.

The program itself lives in the `fns_viewer` package next to this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fns_viewer.server import main  # noqa: E402

if __name__ == '__main__':
    main()
