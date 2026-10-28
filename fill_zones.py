#!/usr/bin/env python3
"""Fill all copper zones in a .kicad_pcb.

Must run under KiCad's bundled interpreter, which is the only one carrying the
pcbnew module:

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" fill_zones.py board.kicad_pcb

gen_signal_pcb.py invokes this automatically after writing a board. Without it
the VLED pour exists but carries no fill polygon, so every via into it reads as
dangling and the board looks unrouted even when it is not.
"""
import sys

import pcbnew


def fill(path):
    board = pcbnew.LoadBoard(path)
    zones = board.Zones()
    filler = pcbnew.ZONE_FILLER(board)
    ok = filler.Fill(zones)
    board.Save(path)
    filled = sum(1 for z in zones if z.IsFilled())
    print("  filled %d/%d zones in %s (filler ok=%s)"
          % (filled, len(zones), path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], ok))
    return 0 if filled == len(zones) else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(max(fill(p) for p in sys.argv[1:]))
