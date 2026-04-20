#!/usr/bin/env python3
"""Goru Font Builder — entry point.

Prints the banner and delegates all work to src.process.
"""

import sys
import argparse
from pathlib import Path

# Make src/ importable without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from src.py.service.processor import Processor
from src.py.utils.build_logger import BuildLogger

# ──────────────────────────── Banner ────────────────────────────
#
# ASCII art that demonstrates the font's core identity:
#   Each Korean glyph (고, 르) is drawn in a 12-column block.
#   Each Latin glyph  (G, o, r, u) is drawn in a 6-column block.
#   This 2:1 ratio is the defining property of Goru Font.
_ART = [
    "━━━━━━━━━━━┓ ━━━━━━━━━━━┓      ┏━━━━━                     ",
    "           ┃            ┃      ┃                          ",
    "           ┃ ┏━━━━━━━━━━┛      ┃  ━━┓ ┏━━━━┓ ┏━━━━┓ ┓    ┏",
    "     ┃     ┃ ┃                 ┃    ┃ ┃    ┃ ┃      ┃    ┃",
    "     ┃       ┗━━━━━━━━━━━      ┃    ┃ ┃    ┃ ┃      ┃    ┃",
    "━━━━━┻━━━━━━ ━━━━━━━━━━━━      ┗━━━━┛ ┗━━━━┛ ┛      ┗━━━━┛",
]

def _print_banner(version: str = "1.0.0") -> None:
    BuildLogger.create(log_to_file=False).print_banner(
        "우리 글자 고르게 고르게", _ART,
        f"고르 · Goru Font Builder v{version} (CJK : Latin = 2 : 1)",
    )


# ──────────────────────────── Entry point ────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Goru Font Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-p", "--profile",
                        nargs="+",
                        metavar="PROFILE",
                        help="Profile(s) to build: mono mono-c absolute-mono … (built sequentially)")
    parser.add_argument("-s", "--styles", nargs="+",
                        metavar="STYLE",
                        help="Styles to build: regular bold italic bold_italic")
    parser.add_argument("-w", "--workers", type=int, default=4,
                        help="Parallel worker count (default: 4)")
    parser.add_argument("-seq", "--sequential", action="store_true",
                        help="Force sequential processing")
    args = parser.parse_args()

    _print_banner()
    return Processor.create().init(args)


if __name__ == "__main__":
    sys.exit(main())
