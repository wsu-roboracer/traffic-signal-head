#!/usr/bin/env python3
"""
Generate KiCad 10 projects for a 1/10 scale traffic signal head LED board.

Board geometry is 1/10 of a standard 12 in (300 mm) three-section signal head:
face 35.6 x 106.7 mm, lens centers 35.6 mm apart, 30 mm lens apertures.

Two variants, selected on the command line:

  ring   36 LEDs, 12 per lens on a single r=11.5 mm ring. Optically the better
         board behind a frosted diffuser: a 12-LED ring already over-lights the
         lens centre, so adding interior LEDs makes uniformity worse, not
         better. ~86% uniform across the 24 mm aperture at a 15 mm standoff.

  dense  57 LEDs, 19 per lens as 1 + 6 + 12 concentric rings. Fills the whole
         aperture for the visible dot-array look of a real modern LED signal
         module, which is designed around a clear or lightly tinted lens at
         near-zero standoff rather than a diffuser. Driven at ~10 mA instead
         of 15 mA so peak current stays level with the ring variant.

In both variants every resistor sits on the FRONT alongside the LEDs, so the
board needs only one assembly setup instead of two — the main cost lever at the
fab. The back carries nothing but the VLED pour.

Usage:  python gen_signal_pcb.py [ring|dense|both]      (default: both)
"""
import math
import os
import re
import subprocess
import sys
import uuid

# ---------------------------------------------------------------- PARAMETERS
BOARD_W = 35.6                     # 1/10 of the 14 in signal face width
BOARD_H = 106.7                    # 1/10 of the 42 in overall height
LENS_Y = [17.8, 53.4, 89.0]        # lens centers from the top edge
LENS_R = 15.0                      # 30 mm lens aperture
# 45 degree corner chamfer, per variant below.
# No mounting holes are generated: add them by hand to suit the housing. A deep
# chamfer and a corner hole are mutually exclusive anyway (beyond ~3.7 mm the cut
# line passes through a hole 3 mm in from the corner).
BX, BY = 50.0, 30.0                # board origin on the pcb sheet

# Hubei KENTO KT-0805 series, JLCPCB basic parts. Symmetric pads at +/-0.9375.
FP_LED = ("LED_SMD", "LED_0805_2012Metric")
# 0805 = 2.0 x 1.25 mm, 0.125 W.  0603 = 1.6 x 0.8 mm, 0.100 W.
FP_RES_0805 = ("Resistor_SMD", "R_0805_2012Metric")
FP_RES_0603 = ("Resistor_SMD", "R_0603_1608Metric")
FP_CONN = ("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical")

VARIANTS = {
    # led_rings / res_rings are [(count, radius)], walked in order. LED n pairs
    # with resistor n, so keep the two lists the same total length and in
    # roughly matching radial order to keep the anode routing short.
    "ring": dict(
        project="signal-head",
        led_rings=[(12, 11.5)],
        res_fp=FP_RES_0805,                     # 0.088 W = 70% of the 0.125 W rating
        res_rings=[(12, 6.0)],                  # inboard, inside the LED ring
        anode_inboard=True,                     # so anodes face their resistors
        conn_back=False,                        # front gap between lenses is clear
        route="inboard",                        # fully routed, see route_inboard()
        chamfer=0.0,                            # plain rectangle
        cols=12,                                # schematic columns per channel
        # 15 mA from a 9 V rail through a ULN2003A (~1 V saturation drop),
        # using the measured Vf of each KENTO part (2.4 / 2.1 / 2.9 V)
        # LED LCSC, then resistor value + LCSC. 0805 390R = C17655 (125 mW),
        # 0805 330R = C17630 (125 mW), both UNI-ROYAL 1% basic parts.
        channels=[("RED", "K_RED", "KT-0805R", "C2295", "390", "C17655"),
                  ("AMB", "K_AMB", "KT-0805Y", "C2296", "390", "C17655"),
                  ("GRN", "K_GRN", "KT-0805G", "C2297", "330", "C17630")],
    ),
    "dense": dict(
        project="signal-head-dense",
        led_rings=[(1, 0.0), (6, 6.0), (12, 11.5)],
        # 0603 rather than 0805: at 0.056 W it runs at 56% of the 0.100 W
        # rating, and the smaller courtyard is what lets the LED rings stay at
        # full aperture fill with a resistor rim outside them.
        res_fp=FP_RES_0603,
        # 19 resistors on one r=15.5 rim, but NOT evenly spaced: the twelve that
        # feed the outer LED ring sit at the same angles as those LEDs so each
        # anode is a plain radial stub, and the remaining seven interleave in
        # the 30 deg gaps. Listed in LED pairing order (centre, inner 6,
        # outer 12).
        res_explicit=([(15.5, -45.0)]
                      + [(15.5, -75.0 + 60.0 * k) for k in range(6)]
                      + [(15.5, -90.0 + 30.0 * k) for k in range(12)]),
        anode_inboard=False,                    # no interior room left
        route="outboard",                       # see route_outboard()
        chamfer=8.0,                            # matches the hand-edited board;
                                                # too deep for corner holes, so the
                                                # mounting holes moved inboard
        conn_back=True,                         # rim rings leave only 1.84 mm
                                                # between lenses on the front
        cols=10,
        # ~10 mA, so 19 LEDs per lens draw about what 12 did at 15 mA
        # 0603 560R = C23204, 0603 470R = C23179, both UNI-ROYAL 1% 100 mW
        channels=[("RED", "K_RED", "KT-0805R", "C2295", "560", "C23204"),
                  ("AMB", "K_AMB", "KT-0805Y", "C2296", "560", "C23204"),
                  ("GRN", "K_GRN", "KT-0805G", "C2297", "470", "C23179")],
    ),
}

KICAD = r"C:\Program Files\KiCad\10.0\share\kicad"
HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------- HELPERS
NS = uuid.UUID("6f1c0f4a-0000-4000-8000-000000000000")
_PREFIX = ""        # set per variant so the two projects never share a uuid


def uid(tag):
    """Deterministic uuid so regenerating does not churn the files."""
    return str(uuid.uuid5(NS, _PREFIX + "/" + tag))


def sexp_extract(text, opener):
    """Return the balanced s-expression starting at the first `opener`."""
    i = text.find(opener)
    if i < 0:
        raise KeyError(opener)
    depth, j = 0, i
    while True:
        c = text[j]
        if c == '"':
            j += 1
            while text[j] != '"' or text[j - 1] == "\\":
                j += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1


def load_symbol(libname, symname):
    path = os.path.join(KICAD, "symbols", libname + ".kicad_sym")
    src = open(path, encoding="utf-8").read()
    body = sexp_extract(src, '(symbol "%s"' % symname)
    return body.replace('(symbol "%s"' % symname,
                        '(symbol "%s:%s"' % (libname, symname), 1)


def load_footprint(libdir, fpname):
    path = os.path.join(KICAD, "footprints", libdir + ".pretty", fpname + ".kicad_mod")
    return open(path, encoding="utf-8").read()


def fnum(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def ring_positions(rings):
    """[(dx, dy, angle_deg)] for concentric rings, walked outward in order.

    A single part at radius 0 is placed dead centre. Rings are started at the
    12 o'clock position so the layout is symmetric about the vertical axis.
    """
    out = []
    for count, radius in rings:
        if radius == 0.0:
            out.append((0.0, 0.0, 0.0))
            if count != 1:
                raise ValueError("radius 0 ring must hold exactly one part")
            continue
        for k in range(count):
            a = math.radians(-90.0 + k * (360.0 / count))
            out.append((radius * math.cos(a), radius * math.sin(a), math.degrees(a)))
    return out


# ---------------------------------------------------------------- SCHEMATIC
def sch_symbol(lib_id, ref, val, fp, x, y, rot, tag, pinnums, project, lcsc=None):
    props = [("Reference", ref, 0), ("Value", val, 0),
             ("Footprint", fp, 1), ("Datasheet", "~", 1), ("Description", "", 1)]
    if lcsc:
        # JLCPCB matches BOM lines on this field
        props.append(("LCSC", lcsc, 1))
    out = ['\t(symbol',
           '\t\t(lib_id "%s")' % lib_id,
           "\t\t(at %s %s %d)" % (fnum(x), fnum(y), rot),
           "\t\t(unit 1)",
           "\t\t(exclude_from_sim no)",
           "\t\t(in_bom yes)",
           "\t\t(on_board yes)",
           "\t\t(dnp no)",
           '\t\t(uuid "%s")' % uid(tag)]
    for i, (key, value, hide) in enumerate(props):
        out.append('\t\t(property "%s" "%s"' % (key, value))
        out.append("\t\t\t(at %s %s 0)" % (fnum(x + 2.54), fnum(y - 5.08 + i * 2.54)))
        if hide:
            out.append("\t\t\t(hide yes)")
        out.append("\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)")
        out.append("\t\t)")
    for p in pinnums:
        out.append('\t\t(pin "%s"\n\t\t\t(uuid "%s")\n\t\t)' % (p, uid(tag + "/pin" + p)))
    out.append('\t\t(instances\n\t\t\t(project "%s"\n\t\t\t\t(path "/%s"'
               % (project, uid("sheet")))
    out.append('\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % ref)
    out.append("\t)")
    return "\n".join(out)


def sch_wire(x1, y1, x2, y2, tag):
    return ("\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n"
            "\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n"
            '\t\t(uuid "%s")\n\t)'
            % (fnum(x1), fnum(y1), fnum(x2), fnum(y2), uid(tag)))


def sch_label(name, x, y, tag, just="left"):
    return ('\t(label "%s"\n\t\t(at %s %s 0)\n\t\t(effects\n\t\t\t(font\n'
            "\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify %s bottom)\n\t\t)\n"
            '\t\t(uuid "%s")\n\t)' % (name, fnum(x), fnum(y), just, uid(tag)))


def sch_text(txt, x, y, tag, size=2.0):
    return ('\t(text "%s"\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size %s %s)\n\t\t\t)\n"
            "\t\t\t(justify left bottom)\n\t\t)\n"
            '\t\t(uuid "%s")\n\t)' % (txt, fnum(x), fnum(y), size, size, uid(tag)))


def build_schematic(cfg):
    project = cfg["project"]
    per_lens = len(ring_positions(cfg["led_rings"]))
    cols = cfg["cols"]
    rows_per_ch = (per_lens + cols - 1) // cols

    lib = [load_symbol("Device", "LED"),
           load_symbol("Device", "R"),
           load_symbol("Connector_Generic", "Conn_01x04")]

    body = []
    x0, y0, pitch_x, pitch_y = 25.4, 40.64, 25.4, 25.4

    body.append(sch_text("1/10 SCALE TRAFFIC SIGNAL HEAD - 3 x %d LEDs PER LENS"
                         % per_lens, 25.4, 20.32, "t/title", 3.0))
    body.append(sch_text("Common anode on VLED. Switch K_RED / K_AMB / K_GRN low side "
                         "(ULN2003A or 2N7000). One resistor per LED.",
                         25.4, 27.94, "t/sub", 1.8))

    for ch, (key, knet, ledval, lcsc, rval, rlcsc) in enumerate(cfg["channels"]):
        ch_row0 = ch * rows_per_ch
        body.append(sch_text("%s - %s - %s ohm" % (key, ledval, rval),
                             10.16, y0 + ch_row0 * pitch_y + 2.0,
                             "t/ch%d" % ch, 1.8))
        for i in range(per_lens):
            n = ch * per_lens + i + 1
            ox = x0 + (i % cols) * pitch_x
            oy = y0 + (ch_row0 + i // cols) * pitch_y
            tag = "%s/%d" % (key, i)
            # resistor, vertical: pin 1 is the top (VLED), pin 2 the bottom
            body.append(sch_symbol("Device:R", "R%d" % n, rval, "%s:%s" % cfg["res_fp"],
                                   ox, oy, 0, "sym/R/" + tag, ["1", "2"], project,
                                   lcsc=rlcsc))
            body.append(sch_wire(ox, oy - 3.81, ox, oy - 6.35, "w/a/" + tag))
            body.append(sch_label("VLED", ox, oy - 6.35, "l/v/" + tag))
            # down and across into the LED anode
            body.append(sch_wire(ox, oy + 3.81, ox, oy + 8.89, "w/b/" + tag))
            body.append(sch_wire(ox, oy + 8.89, ox + 7.62, oy + 8.89, "w/c/" + tag))
            # name the anode net explicitly so it matches the board netlist
            body.append(sch_label("A%d" % n, ox + 3.81, oy + 8.89, "l/a/" + tag))
            # LED rotated 180 so the anode faces left and the cathode right
            body.append(sch_symbol("Device:LED", "D%d" % n, ledval, "%s:%s" % FP_LED,
                                   ox + 11.43, oy + 8.89, 180, "sym/D/" + tag,
                                   ["1", "2"], project, lcsc=lcsc))
            body.append(sch_wire(ox + 15.24, oy + 8.89, ox + 20.32, oy + 8.89, "w/d/" + tag))
            body.append(sch_label(knet, ox + 20.32, oy + 8.89, "l/k/" + tag))

    jx = 40.64
    jy = y0 + (3 * rows_per_ch) * pitch_y + 12.7
    body.append(sch_symbol("Connector_Generic:Conn_01x04", "J1", "Conn_01x04",
                           "%s:%s" % FP_CONN, jx, jy, 0, "sym/J1",
                           ["1", "2", "3", "4"], project))
    for pin, (py, net) in enumerate([(2.54, "VLED"), (0.0, "K_RED"),
                                     (-2.54, "K_AMB"), (-5.08, "K_GRN")]):
        y = jy - py
        body.append(sch_wire(jx - 5.08, y, jx - 10.16, y, "w/j%d" % pin))
        body.append(sch_label(net, jx - 10.16, y, "l/j%d" % pin, just="right"))
    body.append(sch_text("J1 pin 1 = VLED (+9 V)", 25.4, jy + 12.7, "t/j", 1.8))

    return ('(kicad_sch\n\t(version 20250610)\n\t(generator "eeschema")\n'
            '\t(generator_version "10.0")\n\t(uuid "%s")\n\t(paper "A3")\n'
            "\t(lib_symbols\n%s\n\t)\n%s\n"
            '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n)\n'
            % (uid("sheet"), "\n".join(lib), "\n".join(body)))


# --------------------------------------------------------------------- PCB
FLIP = [("F.Cu", "B.Cu"), ("F.Paste", "B.Paste"), ("F.Mask", "B.Mask"),
        ("F.SilkS", "B.SilkS"), ("F.Fab", "B.Fab"), ("F.CrtYd", "B.CrtYd")]


def mirror_geometry(b):
    """KiCad mirrors a back-side footprint by negating local Y.

    Layer renaming alone is enough for parts that are symmetric about Y (an
    0805 has both pads at y=0), but it silently reverses nothing and so leaves
    asymmetric parts - a pin header, a polarised connector - laid out as the
    mirror of what KiCad itself would write. That shows up as a
    lib_footprint_mismatch and, worse, puts the pin-1 marker on the wrong end.
    """
    def neg(m):
        return "%s%s %s)" % (m.group(1), m.group(2), fnum(-float(m.group(3))))
    # (at x y [ang]) keeps its angle sign flipped; plain point pairs just flip Y
    b = re.sub(r"(\((?:at) )([-\d.]+) ([-\d.]+) ([-\d.]+)\)",
               lambda m: "%s%s %s %s)" % (m.group(1), m.group(2),
                                          fnum(-float(m.group(3))),
                                          fnum((-float(m.group(4))) % 360)), b)
    b = re.sub(r"(\((?:at|start|end|center|mid|xy) )([-\d.]+) ([-\d.]+)\)", neg, b)
    return b


def mirror_text(b):
    """Back-layer text must carry (justify mirror) or DRC flags it."""
    out, pos = [], 0
    for m in re.finditer(r"\(effects\b", b):
        if m.start() < pos:
            continue
        blk = sexp_extract(b[m.start():], "(effects")
        out.append(b[pos:m.start()])
        pos = m.start() + len(blk)
        if "justify" not in blk:
            blk = blk[:-1] + "\t(justify mirror)\n\t\t)"
        elif "mirror" not in blk:
            blk = re.sub(r"\(justify ([^)]*)\)", r"(justify \1 mirror)", blk, count=1)
        out.append(blk)
    out.append(b[pos:])
    return "".join(out)


def place_footprint(fpbody, lib, ref, val, x, y, rot, back, netmap, tag, sym_tag,
                    hide_ref=False):
    b = fpbody
    name = re.search(r'^\(footprint "([^"]*)"', b).group(1)
    # board files carry no per-footprint version/generator keys
    b = re.sub(r"\n\t\(version [^)]*\)", "", b)
    b = re.sub(r'\n\t\(generator(_version)? "[^"]*"\)', "", b)
    if back:
        for front, rear in FLIP:
            b = b.replace('"%s"' % front, '"@@%s@@"' % rear)
        b = b.replace("@@", "")
        b = mirror_geometry(b)
        b = mirror_text(b)
    b = re.sub(r'\(property "Reference" "[^"]*"',
               '(property "Reference" "%s"' % ref, b, count=1)
    b = re.sub(r'\(property "Value" "[^"]*"',
               '(property "Value" "%s"' % val, b, count=1)

    # Rewrite each pad: nets, plus an ABSOLUTE rotation. In a .kicad_mod a pad
    # angle is relative to the footprint, but in a .kicad_pcb KiCad stores
    # footprint_rot + pad_rot. Omitting it leaves rectangular pads unrotated
    # while their centers do rotate, which shorts neighbours on a ring.
    out, pos = [], 0
    for m in re.finditer(r'\(pad\s+"[^"]*"', b):
        if m.start() < pos:
            continue
        blk = sexp_extract(b[m.start():], "(pad")
        out.append(b[pos:m.start()])
        pos = m.start() + len(blk)
        num = re.match(r'\(pad\s+"([^"]*)"', blk).group(1)
        pat = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
        blk = blk.replace(pat.group(0), "(at %s %s %s)" % (
            pat.group(1), pat.group(2), fnum((float(pat.group(3) or 0) + rot) % 360)), 1)
        if num in netmap:
            idx, netname = netmap[num]
            blk = blk[:-1] + '\t\t(net %d "%s")\n\t)' % (idx, netname)
        out.append(blk)
    out.append(b[pos:])
    b = "".join(out)

    if hide_ref:
        pm = re.search(r'\(property "Reference" "[^"]*"', b)
        blk = sexp_extract(b[pm.start():], "(property")
        if "(hide yes)" not in blk:
            b = b[:pm.start()] + blk[:-1] + "\t(hide yes)\n\t)" + b[pm.start() + len(blk):]

    head = ('(footprint "%s:%s"\n\t(layer "%s")\n\t(uuid "%s")\n\t(at %s %s %s)\n'
            '\t(path "/%s/%s")'
            % (lib, name, "B.Cu" if back else "F.Cu", uid(tag),
               fnum(x), fnum(y), fnum(rot % 360), uid("sheet"), uid(sym_tag)))
    b = re.sub(r'^\(footprint "[^"]*"\n\t\(layer "[^"]*"\)', head, b, count=1)
    return "\t" + b.replace("\n", "\n\t").rstrip() + "\n"


def seg(x1, y1, x2, y2, width, net, tag, layer="F.Cu"):
    return ('\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width %s)\n'
            '\t\t(layer "%s")\n\t\t(net %d)\n\t\t(uuid "%s")\n\t)'
            % (fnum(x1), fnum(y1), fnum(x2), fnum(y2), fnum(width),
               layer, net, uid(tag)))


def via(x, y, net, tag, size=0.6, drill=0.3):
    return ('\t(via\n\t\t(at %s %s)\n\t\t(size %s)\n\t\t(drill %s)\n'
            '\t\t(layers "F.Cu" "B.Cu")\n\t\t(net %d)\n\t\t(uuid "%s")\n\t)'
            % (fnum(x), fnum(y), fnum(size), fnum(drill), net, uid(tag)))


def route_inboard(cfg, netof, res_pad_off, led_pad):
    """Tracks for the resistors-inboard / anode-inboard topology (ring variant).

    Per lens: a VLED polygon through the resistor inner pads, a radial stub from
    each resistor outer pad to its LED anode pad, and a cathode polygon through
    the LED cathode pads. Pads sit exactly on those radii, so straight segments
    between pad centers land dead on every pad and no via is needed except one
    per lens to drop VLED to the back pour.
    """
    n, led_r = cfg["led_rings"][0]
    _, res_r = cfg["res_rings"][0]
    r_vled = res_r - res_pad_off      # resistor inner pads
    r_anode_r = res_r + res_pad_off   # resistor outer pads
    # With anode_inboard the LED is turned so local +X points at the lens
    # centre: pad 2 (anode) lands inboard, pad 1 (cathode) outboard. Offsets
    # come from the footprint, so swapping LED package reroutes correctly.
    r_anode_l = led_r - led_pad["2"]          # LED pad 2, anode, inboard
    r_cath = led_r + abs(led_pad["1"])        # LED pad 1, cathode, outboard

    cx = BX + BOARD_W / 2.0
    jy = BY + (LENS_Y[0] + LENS_Y[1]) / 2.0
    jpad = [(BX + BOARD_W / 2.0 - 3.81 + 2.54 * k, jy) for k in range(4)]
    x_chan = BX + BOARD_W - 2.1       # clear channel by the right board edge

    out = []
    for ch, (key, knet, _, _, _, _) in enumerate(cfg["channels"]):
        cy = BY + LENS_Y[ch]
        kn = netof[knet]
        ang = [math.radians(-90.0 + k * (360.0 / n)) for k in range(n)]
        for k in range(n):
            a, b = ang[k], ang[(k + 1) % n]
            t = "%s/%d" % (key, k)
            for r, w, net, nm in ((r_vled, 0.5, netof["VLED"], "v"),
                                  (r_cath, 0.5, kn, "k")):
                out.append(seg(cx + r * math.cos(a), cy + r * math.sin(a),
                               cx + r * math.cos(b), cy + r * math.sin(b),
                               w, net, "trk/%s/%s" % (nm, t)))
            anet = netof["A%d" % (ch * n + k + 1)]
            out.append(seg(cx + r_anode_r * math.cos(a), cy + r_anode_r * math.sin(a),
                           cx + r_anode_l * math.cos(a), cy + r_anode_l * math.sin(a),
                           0.3, anet, "trk/a/" + t))
        # VLED polygon down to the lens centre, then a via to the back pour
        out.append(seg(cx, cy - r_vled, cx, cy, 0.5, netof["VLED"], "trk/vc/%d" % ch))
        out.append(via(cx, cy, netof["VLED"], "via/v/%d" % ch))

    # cathode trunks out to J1. Red and amber reach it straight through the
    # inter-lens gaps; green has the amber lens in the way and takes the right
    # hand channel instead.
    cy0, cy1, cy2 = (BY + y for y in LENS_Y)
    out.append(seg(cx, cy0 + r_cath, jpad[1][0], jy, 0.6, netof["K_RED"], "trk/t/red"))
    out.append(seg(cx, cy1 - r_cath, jpad[2][0], jy, 0.6, netof["K_AMB"], "trk/t/amb"))
    out.append(seg(cx + r_cath, cy2, x_chan, cy2, 0.6, netof["K_GRN"], "trk/t/grn1"))
    out.append(seg(x_chan, cy2, x_chan, jy, 0.6, netof["K_GRN"], "trk/t/grn2"))
    out.append(seg(x_chan, jy, jpad[3][0], jy, 0.6, netof["K_GRN"], "trk/t/grn3"))
    return out


def route_outboard(cfg, netof, res_pad_off, led_pad):
    """Tracks for the resistors-outboard / anode-outboard topology (dense).

    Harder than the ring board. The outer twelve anodes are plain radial stubs,
    but the centre LED and the inner six are radially *blocked*: the direct path
    out to the rim crosses the outer LED ring and, worse, the outer cathode
    polygon. Those seven step sideways to the gap angle between outer LEDs and
    then run on the BACK, which is empty apart from the VLED pour.
    """
    pa = led_pad["2"]                 # +0.9375, anode offset, outboard here
    pk = abs(led_pad["1"])            # 0.9375, cathode offset, inboard
    rings = cfg["led_rings"]
    r_in, r_out = rings[1][1], rings[2][1]
    res_r = cfg["res_explicit"][0][0]
    r_res_a = res_r - res_pad_off     # resistor anode pad, inboard
    r_res_v = res_r + res_pad_off     # resistor VLED pad, outboard
    r_via2 = 13.6                     # between outer LED pads and resistor pads
    cx = BX + BOARD_W / 2.0

    def P(cy, r, deg):
        a = math.radians(deg)
        return cx + r * math.cos(a), cy + r * math.sin(a)

    out = []
    for ch, (key, knet, _, _, _, _) in enumerate(cfg["channels"]):
        cy = BY + LENS_Y[ch]
        kn, vn = netof[knet], netof["VLED"]
        t0 = "%s" % key
        inner_a = [-90.0 + 60.0 * k for k in range(6)]
        outer_a = [-90.0 + 30.0 * k for k in range(12)]
        res_a = [p[1] for p in cfg["res_explicit"]]

        # --- cathodes: hexagon, 12-gon, and links in to the centre pad -------
        for i, a in enumerate(inner_a):
            b = inner_a[(i + 1) % 6]
            out.append(seg(*P(cy, r_in - pk, a), *P(cy, r_in - pk, b), 0.4, kn,
                           "d/kh/%s/%d" % (t0, i)))
        for i, a in enumerate(outer_a):
            b = outer_a[(i + 1) % 12]
            out.append(seg(*P(cy, r_out - pk, a), *P(cy, r_out - pk, b), 0.5, kn,
                           "d/ko/%s/%d" % (t0, i)))
        # hexagon -> 12-gon at -60 deg: a 12-gon vertex with no inner LED on it
        chord_in = (r_in - pk) * math.cos(math.radians(30.0))
        out.append(seg(*P(cy, chord_in, -60.0), *P(cy, r_out - pk, -60.0), 0.4, kn,
                       "d/klink/%s" % t0))
        # centre cathode pad -> hexagon chord at 180 deg, likewise clear
        out.append(seg(*P(cy, pk, 180.0), *P(cy, chord_in, 180.0), 0.4, kn,
                       "d/kc/%s" % t0))

        # --- anodes -----------------------------------------------------------
        for i in range(19):
            n = ch * 19 + i + 1
            an = netof["A%d" % n]
            ra = res_a[i]
            tag = "%s/%d" % (t0, i)
            if i >= 7:                                   # outer twelve: radial
                la = outer_a[i - 7]
                out.append(seg(*P(cy, r_out + pa, la), *P(cy, r_res_a, la),
                               0.3, an, "d/ao/" + tag))
                continue
            # centre + inner six: sidestep to the resistor's angle, then back side
            if i == 0:
                v1r, v1a = 1.9, ra
                out.append(seg(*P(cy, pa, 0.0), *P(cy, v1r, v1a), 0.3, an,
                               "d/ac0/" + tag))
            else:
                v1r, v1a = r_in + pa, ra
                out.append(seg(*P(cy, r_in + pa, inner_a[i - 1]), *P(cy, v1r, v1a),
                               0.3, an, "d/ai/" + tag))
            out.append(via(*P(cy, v1r, v1a), an, "d/v1/" + tag))
            out.append(seg(*P(cy, v1r, v1a), *P(cy, r_via2, ra), 0.3, an,
                           "d/ab/" + tag, layer="B.Cu"))
            out.append(via(*P(cy, r_via2, ra), an, "d/v2/" + tag))
            out.append(seg(*P(cy, r_via2, ra), *P(cy, r_res_a, ra), 0.3, an,
                           "d/af/" + tag))

        # --- VLED rim polygon, plus one via down to the back pour -------------
        order = sorted(range(19), key=lambda i: res_a[i] % 360.0)
        for j, i in enumerate(order):
            k = order[(j + 1) % 19]
            out.append(seg(*P(cy, r_res_v, res_a[i]), *P(cy, r_res_v, res_a[k]),
                           0.5, vn, "d/v/%s/%d" % (t0, j)))
        # chord midpoint of the 0..30 deg gap, on the right where nothing runs
        out.append(via(*P(cy, r_res_v * math.cos(math.radians(15.0)), 15.0), vn,
                       "d/vv/%s" % t0))

        # --- cathode via out to the back, at a chord angle nothing else uses --
        kv_r = (r_out - pk) * math.cos(math.radians(15.0))
        out.append(via(*P(cy, kv_r, 195.0), kn, "d/kv/%s" % t0))

    # --- back-side trunks from each cathode via to J1 -------------------------
    # J1 sits on the back, pads running left from pin 1: VLED 63.99, K_RED 61.45,
    # K_AMB 58.91, K_GRN 56.37, all at y = 65.6.
    jy = BY + (LENS_Y[0] + LENS_Y[1]) / 2.0
    jx = BX + BOARD_W / 2.0 - 3.81
    trunks = [("K_RED", 0, 53.5, 63.0, jx - 2.54),
              ("K_AMB", 1, 52.5, 69.0, jx - 5.08),
              ("K_GRN", 2, 51.5, 67.5, jx - 7.62)]
    for knet, ch, lane, lane_y, padx in trunks:
        cy = BY + LENS_Y[ch]
        kn = netof[knet]
        kv_r = (r_out - pk) * math.cos(math.radians(15.0))
        vx, vy = P(cy, kv_r, 195.0)
        out.append(seg(vx, vy, lane, vy, 0.5, kn, "d/t1/%s" % knet, layer="B.Cu"))
        out.append(seg(lane, vy, lane, lane_y, 0.5, kn, "d/t2/%s" % knet, layer="B.Cu"))
        out.append(seg(lane, lane_y, padx, lane_y, 0.5, kn, "d/t3/%s" % knet, layer="B.Cu"))
        out.append(seg(padx, lane_y, padx, jy, 0.5, kn, "d/t4/%s" % knet, layer="B.Cu"))
    return out


def build_pcb(cfg):
    fp_led = load_footprint(*FP_LED)
    fp_res = load_footprint(*cfg["res_fp"])
    fp_conn = load_footprint(*FP_CONN)

    # pad offset of the chosen resistor package, read from the footprint
    res_pad_off = max(abs(float(re.search(r"\(at ([-\d.]+)",
                                          sexp_extract(fp_res[m.start():], "(pad")).group(1)))
                      for m in re.finditer(r'\(pad\s+"[^"]*"', fp_res))

    led_pos = ring_positions(cfg["led_rings"])
    if "res_explicit" in cfg:
        res_pos = [(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), a)
                   for r, a in cfg["res_explicit"]]
    else:
        res_pos = ring_positions(cfg["res_rings"])
    if len(led_pos) != len(res_pos):
        raise ValueError("led_rings and res_rings must hold the same part count "
                         "(%d vs %d)" % (len(led_pos), len(res_pos)))
    per_lens = len(led_pos)
    # 180 deg puts the LED anode pad inboard, toward interior resistors.
    led_flip = 180.0 if cfg.get("anode_inboard") else 0.0
    # Resistors outboard of the LEDs need turning too, so that pad 2 (the anode
    # end) faces inward at the LEDs rather than out at the board edge. Keeps the
    # schematic pin assignment intact, unlike swapping the nets.
    res_flip = 0.0 if cfg.get("anode_inboard") else 180.0

    nets = ["", "VLED", "K_RED", "K_AMB", "K_GRN"]
    anode = {}
    for ch in range(len(cfg["channels"])):
        for i in range(per_lens):
            n = ch * per_lens + i + 1
            anode[n] = len(nets)
            nets.append("A%d" % n)

    fps, items = [], []
    for ch, (key, knet, ledval, lcsc, rval, rlcsc) in enumerate(cfg["channels"]):
        cx, cy = BX + BOARD_W / 2.0, BY + LENS_Y[ch]
        for i in range(per_lens):
            n = ch * per_lens + i + 1
            tag = "%s/%d" % (key, i)
            anet = (anode[n], "A%d" % n)
            # LED on the front, long axis radial. With anode_inboard the part is
            # turned so pad 2 (A) faces the centre and pad 1 (K) faces out;
            # otherwise the reverse. A centre part has no radial direction.
            ldx, ldy, lang = led_pos[i]
            fps.append(place_footprint(
                fp_led, FP_LED[0], "D%d" % n, ledval,
                cx + ldx, cy + ldy, -lang + led_flip, False,
                {"1": (nets.index(knet), knet), "2": anet},
                "fp/D/" + tag, "sym/D/" + tag, hide_ref=True))
            # Resistor on the FRONT, same side as the LEDs, so the board takes
            # one assembly setup rather than two. Its VLED pad needs a via down
            # to the back pour.
            rdx, rdy, rang = res_pos[i]
            fps.append(place_footprint(
                fp_res, cfg["res_fp"][0], "R%d" % n, rval,
                cx + rdx, cy + rdy, -rang + res_flip, False,
                {"1": (1, "VLED"), "2": anet},
                "fp/R/" + tag, "sym/R/" + tag, hide_ref=True))
        # lens aperture, as a reference circle on the drawings layer
        items.append('\t(gr_circle\n\t\t(center %s %s)\n\t\t(end %s %s)\n'
                     "\t\t(stroke\n\t\t\t(width 0.12)\n\t\t\t(type dash)\n\t\t)\n"
                     '\t\t(fill no)\n\t\t(layer "Dwgs.User")\n\t\t(uuid "%s")\n\t)'
                     % (fnum(cx), fnum(cy), fnum(cx + LENS_R), fnum(cy),
                        uid("lens/%d" % ch)))
        items.append('\t(gr_text "%s"\n\t\t(at %s %s 0)\n\t\t(layer "B.SilkS" knockout)\n'
                     '\t\t(uuid "%s")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.4 1.4)\n'
                     "\t\t\t\t(thickness 0.25)\n\t\t\t)\n\t\t\t(justify mirror)\n\t\t)\n\t)"
                     # 10 mm sits in the clear annulus on the back for both
                     # variants: outside the dense inner resistor ring (r=5.2)
                     # and inside the outer one (r=15.0).
                     % ("%s %sR" % (key, rval), fnum(cx), fnum(cy + 10.0),
                        uid("lbl/%d" % ch)))

    # 4-pin header in the gap between the red and amber lenses. Through-hole, so
    # which side it is nominally on does not affect the single-sided SMD run.
    fps.append(place_footprint(
        fp_conn, FP_CONN[0], "J1", "VLED/R/A/G",
        BX + BOARD_W / 2.0 - 3.81, BY + (LENS_Y[0] + LENS_Y[1]) / 2.0, 90,
        bool(cfg.get("conn_back")),
        {"1": (1, "VLED"), "2": (2, "K_RED"), "3": (3, "K_AMB"), "4": (4, "K_GRN")},
        "fp/J1", "sym/J1"))

    # Outline with 45 degree corner chamfers. CHAMFER=0 gives a plain rectangle.
    # The limit is the M2 holes 3 mm in from each corner: beyond about 3.7 mm the
    # chamfer starts eating into them.
    c = cfg.get("chamfer", 0.0)
    x0, y0 = BX, BY
    x1, y1 = BX + BOARD_W, BY + BOARD_H
    if c > 0:
        pts = [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c),
               (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)]
    else:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        items.append('\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n'
                     "\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type default)\n\t\t)\n"
                     '\t\t(layer "Edge.Cuts")\n\t\t(uuid "%s")\n\t)'
                     % (fnum(ax), fnum(ay), fnum(bx), fnum(by), uid("edge%d" % i)))

    zpts = [(BX + 0.5, BY + 0.5), (BX + BOARD_W - 0.5, BY + 0.5),
            (BX + BOARD_W - 0.5, BY + BOARD_H - 0.5), (BX + 0.5, BY + BOARD_H - 0.5)]
    items.append('\t(zone\n\t\t(net 1)\n\t\t(net_name "VLED")\n\t\t(layers "B.Cu")\n'
                 '\t\t(uuid "%s")\n\t\t(name "VLED")\n\t\t(hatch edge 0.5)\n'
                 "\t\t(connect_pads\n\t\t\t(clearance 0.3)\n\t\t)\n"
                 "\t\t(min_thickness 0.25)\n\t\t(filled_areas_thickness no)\n"
                 "\t\t(fill yes\n\t\t\t(thermal_gap 0.3)\n\t\t\t(thermal_bridge_width 0.4)\n\t\t)\n"
                 "\t\t(polygon\n\t\t\t(pts\n\t\t\t\t%s\n\t\t\t)\n\t\t)\n\t)"
                 % (uid("zone/vled"),
                    " ".join("(xy %s %s)" % (fnum(a), fnum(b)) for a, b in zpts)))

    if cfg.get("route") == "outboard":
        netof = {nm: i for i, nm in enumerate(nets)}
        led_pad = {re.match(r'\(pad\s+"([^"]*)"', blk).group(1):
                   float(re.search(r"\(at ([-\d.]+)", blk).group(1))
                   for blk in (sexp_extract(fp_led[m.start():], "(pad")
                               for m in re.finditer(r'\(pad\s+"[^"]*"', fp_led))}
        items += route_outboard(cfg, netof, res_pad_off, led_pad)

    if cfg.get("route") == "inboard":
        netof = {nm: i for i, nm in enumerate(nets)}
        led_pad = {re.match(r'\(pad\s+"([^"]*)"', blk).group(1):
                   float(re.search(r"\(at ([-\d.]+)", blk).group(1))
                   for blk in (sexp_extract(fp_led[m.start():], "(pad")
                               for m in re.finditer(r'\(pad\s+"[^"]*"', fp_led))}
        items += route_inboard(cfg, netof, res_pad_off, led_pad)

    layers = ('\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n'
              '\t\t(9 "F.Adhes" user "F.Adhesive")\n\t\t(11 "B.Adhes" user "B.Adhesive")\n'
              '\t\t(13 "F.Paste" user)\n\t\t(15 "B.Paste" user)\n'
              '\t\t(5 "F.SilkS" user "F.Silkscreen")\n\t\t(7 "B.SilkS" user "B.Silkscreen")\n'
              '\t\t(1 "F.Mask" user)\n\t\t(3 "B.Mask" user)\n'
              '\t\t(17 "Dwgs.User" user "User.Drawings")\n\t\t(19 "Cmts.User" user "User.Comments")\n'
              '\t\t(21 "Eco1.User" user "User.Eco1")\n\t\t(23 "Eco2.User" user "User.Eco2")\n'
              '\t\t(25 "Edge.Cuts" user)\n\t\t(27 "Margin" user)\n'
              '\t\t(31 "F.CrtYd" user "F.Courtyard")\n\t\t(29 "B.CrtYd" user "B.Courtyard")\n'
              '\t\t(35 "F.Fab" user)\n\t\t(33 "B.Fab" user)\n\t)')
    # Keep setup minimal: KiCad 10 rejects allow_soldermask_bridges here, and
    # fills in stackup/pcbplotparams defaults itself on first save.
    # Auxiliary origin at the board's bottom-left corner. Exporting gerbers,
    # drill and the pick-and-place file with --use-drill-file-origin then puts
    # all three in one coordinate system with every coordinate positive. Without
    # this the flag silently falls back to the sheet origin and the CPL comes
    # out with negative Y.
    setup = ("\t(setup\n\t\t(pad_to_mask_clearance 0)\n"
             "\t\t(aux_axis_origin %s %s)\n\t)"
             % (fnum(BX), fnum(BY + BOARD_H)))
    netblk = "\n".join('\t(net %d "%s")' % (i, n) for i, n in enumerate(nets))

    return ('(kicad_pcb\n\t(version 20241229)\n\t(generator "pcbnew")\n'
            '\t(generator_version "10.0")\n'
            "\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n"
            '\t(paper "A4")\n%s\n%s\n%s\n%s%s\n)\n'
            % (layers, setup, netblk, "".join(fps), "\n".join(items)))


# -------------------------------------------------------------------- WRITE
def generate(name):
    global _PREFIX
    cfg = VARIANTS[name]
    project = cfg["project"]
    _PREFIX = project
    outdir = os.path.join(HERE, project)
    os.makedirs(outdir, exist_ok=True)

    sch, pcb = build_schematic(cfg), build_pcb(cfg)
    open(os.path.join(outdir, project + ".kicad_sch"), "w", encoding="utf-8").write(sch)
    open(os.path.join(outdir, project + ".kicad_pcb"), "w", encoding="utf-8").write(pcb)

    # Only create the project file if absent. Once KiCad has opened the project
    # it rewrites this with its full default design-rule set, which is richer
    # than the stub below and must not be clobbered on regeneration.
    pro = os.path.join(outdir, project + ".kicad_pro")
    if os.path.exists(pro):
        print("  kept existing kicad_pro (%d bytes)" % os.path.getsize(pro))
    else:
        open(pro, "w", encoding="utf-8").write(
            '{\n  "board": {"design_settings": {"rules": {"min_clearance": 0.2,'
            ' "min_track_width": 0.2, "min_via_diameter": 0.6,'
            ' "min_through_hole_diameter": 0.3}}},\n'
            '  "meta": {"filename": "%s.kicad_pro", "version": 3},\n'
            '  "net_settings": {"classes": [{"name": "Default", "clearance": 0.2,'
            ' "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3}]},\n'
            '  "sheets": [["%s", "Root"]],\n  "text_variables": {}\n}\n'
            % (project, uid("sheet")))

    # Fill the copper zones. Without this the VLED pour exists but carries no
    # fill polygon, so every via into it reads as dangling and a fully routed
    # board still reports unconnected items. Needs KiCad's own interpreter,
    # which is the only one with pcbnew.
    kpy = os.path.normpath(os.path.join(KICAD, "..", "..", "bin", "python.exe"))
    filler = os.path.join(HERE, "fill_zones.py")
    if os.path.exists(kpy) and os.path.exists(filler):
        r = subprocess.run([kpy, filler, os.path.join(outdir, project + ".kicad_pcb")],
                           capture_output=True, text=True)
        print((r.stdout or r.stderr).rstrip() or "  zone fill produced no output")
    else:
        print("  NOTE: zone fill skipped (no KiCad python); press B in pcbnew")

    # A stale autosave makes KiCad offer to "recover" the pre-regeneration
    # schematic on next open, which would silently undo this run.
    auto = os.path.join(outdir, "_autosave-" + project + ".kicad_sch")
    if os.path.exists(auto):
        os.remove(auto)
        print("  removed stale autosave")

    per_lens = len(ring_positions(cfg["led_rings"]))
    print("  %-18s %d LEDs (%d per lens), %d resistors  ->  %s"
          % (name, per_lens * 3, per_lens, per_lens * 3, outdir))


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    names = list(VARIANTS) if which == "both" else [which]
    for n in names:
        if n not in VARIANTS:
            raise SystemExit("unknown variant %r, expected one of %s or 'both'"
                             % (n, ", ".join(VARIANTS)))
    for n in names:
        generate(n)


if __name__ == "__main__":
    main()
