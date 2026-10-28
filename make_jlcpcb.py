#!/usr/bin/env python3
"""
Build JLCPCB production files for a signal-head variant.

    python make_jlcpcb.py [ring|dense|both]      (default: both)

Produces, per variant, into <project>/jlcpcb/:

    <project>-gerbers.zip   fabrication gerbers + Excellon drill
    <project>-bom.csv       assembly BOM      (Comment, Designator, Footprint, LCSC Part #)
    <project>-cpl.csv       pick and place    (Designator, Mid X, Mid Y, Layer, Rotation)

Only SMD parts reach the BOM and CPL. The mounting holes are not components and
J1 is through-hole, so both are dropped from the assembly files and listed in
the console summary instead -- fit J1 by hand.

Gerbers, drill and CPL are all exported against the board's auxiliary origin,
which gen_signal_pcb.py puts at the bottom-left corner. That keeps the three in
one coordinate system and makes every CPL coordinate positive.
"""
import csv
import io
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

PROJECTS = {"ring": "signal-head", "dense": "signal-head-dense"}

# Fabrication layers JLCPCB expects for a 2 layer board.
LAYERS = ("F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts")


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("FAILED: %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout.strip()


def gerbers(pcb, outdir, project):
    """Plot gerbers + drill into a scratch dir and zip them."""
    work = os.path.join(outdir, "_gerber")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    run([CLI, "pcb", "export", "gerbers", "-o", work, "-l", LAYERS,
         "--no-protel-ext", "--check-zones", "--use-drill-file-origin", pcb])
    run([CLI, "pcb", "export", "drill", "-o", work, "--format", "excellon",
         "--drill-origin", "plot", "--excellon-units", "mm",
         "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", pcb])
    zp = os.path.join(outdir, project + "-gerbers.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(work)):
            z.write(os.path.join(work, fn), fn)
    n = len(zipfile.ZipFile(zp).namelist())
    shutil.rmtree(work, ignore_errors=True)
    return zp, n


def bom(sch, outdir, project):
    """KiCad grouped BOM -> JLCPCB assembly BOM."""
    tmp = os.path.join(outdir, "_bom.csv")
    run([CLI, "sch", "export", "bom", "-o", tmp,
         "--fields", "${QUANTITY},Reference,Value,Footprint,LCSC",
         "--labels", "Qty,Designator,Comment,Footprint,LCSC",
         "--group-by", "Value,LCSC", "--ref-range-delimiter", "", sch])
    rows, skipped = [], []
    with open(tmp, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            desig = r["Designator"].strip()
            # drop the mounting holes and the through-hole header
            if desig.startswith("H") or desig.startswith("J"):
                skipped.append(desig)
                continue
            rows.append({"Comment": r["Comment"].strip(),
                         "Designator": desig,
                         "Footprint": r["Footprint"].split(":")[-1],
                         "LCSC Part #": r["LCSC"].strip()})
    os.remove(tmp)
    out = os.path.join(outdir, project + "-bom.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["Comment", "Designator", "Footprint", "LCSC Part #"])
        w.writeheader()
        w.writerows(rows)
    return out, rows, skipped


def cpl(pcb, outdir, project):
    """KiCad position file -> JLCPCB CPL. SMD only, mm, absolute origin."""
    tmp = os.path.join(outdir, "_pos.csv")
    run([CLI, "pcb", "export", "pos", "-o", tmp, "--format", "csv",
         "--units", "mm", "--side", "both", "--smd-only", "--exclude-fp-th",
         "--use-drill-file-origin", pcb])
    rows = []
    with open(tmp, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = {k.strip().lower(): (v or "").strip() for k, v in r.items()}
            rows.append({"Designator": g["ref"],
                         "Mid X": g["posx"],
                         "Mid Y": g["posy"],
                         "Layer": "Top" if g["side"].lower() == "top" else "Bottom",
                         "Rotation": g["rot"]})
    os.remove(tmp)
    out = os.path.join(outdir, project + "-cpl.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writeheader()
        w.writerows(rows)
    return out, rows


def build(key):
    project = PROJECTS[key]
    base = os.path.join(HERE, project)
    pcb = os.path.join(base, project + ".kicad_pcb")
    sch = os.path.join(base, project + ".kicad_sch")
    for f in (pcb, sch):
        if not os.path.exists(f):
            raise SystemExit("missing %s -- run gen_signal_pcb.py first" % f)
    outdir = os.path.join(base, "jlcpcb")
    os.makedirs(outdir, exist_ok=True)

    print("=" * 66)
    print("%s  (%s)" % (project, key))
    zp, nz = gerbers(pcb, outdir, project)
    print("  gerbers : %-34s %2d files" % (os.path.basename(zp), nz))
    bp, brows, skipped = bom(sch, outdir, project)
    print("  bom     : %-34s %2d lines, %d parts"
          % (os.path.basename(bp), len(brows),
             sum(len(r["Designator"].split(",")) for r in brows)))
    cp, crows = cpl(pcb, outdir, project)
    print("  cpl     : %-34s %2d placements" % (os.path.basename(cp), len(crows)))

    # cross-check: every BOM designator must appear in the CPL and vice versa
    bset = set()
    for r in brows:
        bset.update(d.strip() for d in r["Designator"].split(",") if d.strip())
    cset = {r["Designator"] for r in crows}
    if bset != cset:
        print("  WARNING  BOM/CPL mismatch")
        if bset - cset:
            print("    in BOM only : %s" % ", ".join(sorted(bset - cset)[:12]))
        if cset - bset:
            print("    in CPL only : %s" % ", ".join(sorted(cset - bset)[:12]))
    else:
        print("  check   : BOM and CPL agree on all %d designators" % len(bset))
    if skipped:
        print("  hand-fit: %s (not in the SMT files)" % ", ".join(sorted(set(skipped))))
    return outdir


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    keys = list(PROJECTS) if which == "both" else [which]
    for k in keys:
        if k not in PROJECTS:
            raise SystemExit("unknown variant %r; expected ring, dense or both" % k)
    for k in keys:
        build(k)
    print("=" * 66)
    print("Before ordering: open JLCPCB's assembly preview and confirm every LED "
          "cathode\nfaces OUTBOARD (ring board) / INBOARD (dense board). JLCPCB's "
          "library\norientation does not always match KiCad's, and a 180 deg LED "
          "error is the\nmost common way an otherwise correct board comes back dead.")


if __name__ == "__main__":
    main()
