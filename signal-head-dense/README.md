# 1/10 Scale Traffic Signal Head — LED Board, **dense variant**

57 LEDs, 19 per lens, filling the full 30 mm aperture.

This is the alternative to [`../signal-head/`](../signal-head/), which uses a
single 12-LED ring. Both come from the same generator:

```
python ../gen_signal_pcb.py dense     # this board
python ../gen_signal_pcb.py ring      # the ring variant
python ../gen_signal_pcb.py both
```

## Which variant to build

They are optimised for **different optics**, not different quality levels.

| | ring | dense (this one) |
|---|---|---|
| LEDs | 36 (12/lens) | **57 (19/lens)** |
| Resistors | 36 × 0805 | 57 × **0603** |
| Lens | frosted **diffuser** | **clear or lightly tinted** |
| Standoff | ~15 mm | near zero |
| Uniformity, 24 mm aperture | **~86%** | 64% |
| Look | even glowing disc | **visible dot array** |
| Peak current | ~186 mA | ~207 mA |
| SMD placements | 72 | **114** |
| J1 | front | back |

A 12-LED ring already over-lights the lens centre, so on a diffused board
adding interior LEDs measurably *hurts* uniformity — see the analysis in the
[ring README](../signal-head/README.md#why-the-ring-has-no-interior-leds).

So this board is not for use behind a diffuser. It is for the other design:
**the LEDs are the visible image**, the way a real modern 12 in LED signal
module works. There the array has to fill the aperture, because you are looking
straight at the dots. Uniformity of a notional diffused disc is irrelevant.

## Board

| | |
|---|---|
| Size | **35.6 × 106.7 mm** (1/10 of the 14 × 42 in signal face) |
| Lens centers | 17.8 / 53.4 / 89.0 mm from the top edge |
| LEDs | 57 × `LED_0805_2012Metric` (**KENTO KT-0805**), front: **1 centre + 6 @ r=6.0 + 12 @ r=11.5 mm** |
| Resistors | 57 × `R_0603_1608Metric` (**0603, 1.6 × 0.8 mm**), **front**, r=15.5 mm |
| Connector | J1, 4-pin 2.54 mm header, **back** |
| Mounting | 4 × M2 (2.2 mm), 3 mm in from each corner |
| Layers | 2 — the back carries the VLED pour and J1 only |

**Every placed SMD part is on the front.** Single-sided placement is one
assembly setup instead of two. J1 is through-hole, so it takes no part in the
SMD run and sitting on the back costs nothing.

Dot spacing comes out close to even, which is what sells the look:

| | |
|---|---|
| centre → inner ring | 6.00 mm |
| inner ring neighbours | 6.28 mm |
| inner → outer ring | 5.50 mm |
| outer ring neighbours | 6.02 mm |
| outer LED pad edge | r = 13.50 mm (1.5 mm inside the aperture) |

### Why 0603 here and 0805 on the ring board

Not a preference — a constraint, twice over.

**Thermal.** At ~10 mA these dissipate up to 0.062 W, which is 62% of 0603's
0.100 W rating. The ring board's legs dissipate 0.089 W, which would be 89% of
0603 and 142% of 0402 — so that board stays on 0805. Going below 0603 here is also out:
0402 would run at 90% of rating.

**Area.** The dense front has no interior room left, so all 57 resistors have to
live on a rim outside the LED rings. 0805's courtyard forced either the LED
rings inward (shrinking the dot field) or the resistors outward to within
0.75 mm of the board edge. 0603's smaller courtyard is what lets the rings stay
at full aperture fill with a clean 1.08 mm edge margin.

Package size does not change machine-assembly cost, only board area and thermal
headroom.

### Why J1 is on the back

The resistor rim rings leave only **1.6 mm** between adjacent lenses on the
front — not enough for a connector. The back is otherwise empty, and a
through-hole part is a separate soldering operation regardless of side, so
nothing is lost.

## Electrical

Identical topology to the ring variant — common anode, low-side switched,
one resistor per LED:

```
VLED (+9 V) --> R(n) --> LED(n) anode
                         LED(n) cathode --> K_RED / K_AMB / K_GRN --> switch --> GND
```

| Net | Nodes | |
|---|---|---|
| `VLED` | 58 | 57 resistors + J1.1 |
| `K_RED` | 20 | 19 cathodes + J1.2 |
| `K_AMB` | 20 | 19 cathodes + J1.3 |
| `K_GRN` | 20 | 19 cathodes + J1.4 |
| `A1`–`A57` | 2 each | one resistor to one LED anode |

**Values are lower-current than the ring variant on purpose.** 19 LEDs at the
ring board's 15 mA would be 285 mA — too much for a 9 V PP3. Dropping to ~10 mA
keeps peak draw level with the 12-LED board while putting 58% more emitters
behind the lens:

| Color | Part | LCSC | Vf | R | Actual | Per lens | Dissipation |
|---|---|---|---|---|---|---|---|
| Red, D1–D19 | KT-0805R | **C2295** | 2.4 V | 560 Ω | 10.0 mA | 190 mA | 0.056 W (56%) |
| Amber, D20–D38 | KT-0805Y | **C2296** | 2.1 V | 560 Ω | 10.5 mA | 200 mA | 0.062 W (62%) |
| Green, D39–D57 | KT-0805G | **C2297** | 2.9 V | 470 Ω | 10.9 mA | 207 mA | 0.055 W (55%) |

Assumes a ULN2003A with ~1 V saturation drop.

Only one color is lit at a time: **~207 mA peak** (green). Part selection and brightness figures are in the [ring README](../signal-head/README.md#parts--jlcpcb).

## Verification

```
sch erc  ->  0 violations
pcb drc  ->  0 violations, schematic parity 0
```

The 171 reported "unconnected items" are the **intentionally unrouted**
ratsnest: 57 anodes + 3 × 19 cathodes + 57 VLED pads (the last 57 disappear
once the back zone is filled and the VLED vias are placed).

## What is left to do

1. **Fill zones** — open the PCB and press `B`.
2. **Route.** Radii from each lens centre; all LED and resistor pads are on the
   front. Unlike the ring board, anodes face **outboard** here, toward the
   resistor rim:

   | | r |
   |---|---|
   | Centre LED cathode / anode | 0.9375 mm either side |
   | Inner-ring cathode / anode | 5.0625 / 6.9375 mm |
   | Outer-ring cathode / anode | **10.5625** / 12.4375 mm |
   | Resistor inner / outer pads | 14.675 / 16.325 mm |

   - **Outer 12 anodes** are easy: a straight radial track from the anode pad
     to its resistor's inner pad, 1.825 mm of clear gap, no via.
   - **Centre and inner 6 anodes** are the awkward ones — they have to get past
     the outer LED ring. The inner LEDs sit at 60° spacing and the outer ones
     at 30°, so each inner LED is radially *aligned* with an outer one and the
     direct path is blocked. Either thread diagonally through the 3.82 mm
     tangential gaps at ±15°, or drop a via and run these seven on the back,
     which is far easier since the back is empty.
   - **Cathodes**: three groups per lens — the centre pad, a hexagon through the
     six inner cathode pads at r = 5.0625 mm, and a 12-gon through the outer
     cathode pads at r = 10.5625 mm. Pads sit exactly on those radii.
   - **VLED**: a 19-gon through the resistor outer pads at r = 16.325 mm, plus
     one via per lens to the back pour. J1's VLED pin is through-hole and
     touches the pour directly.
3. **Lens choice.** This board wants a clear or lightly tinted lens at near-zero
   standoff. Putting it behind a frosted diffuser throws away the reason it
   exists and gives worse uniformity than the ring board.
4. **White soldermask** still helps, though less than on the ring board, since
   far less light reaches the substrate between dots.

## Fab notes

Same 35.6 × 106.7 mm size as the ring variant, so the same 100 × 100 mm budget
tier overrun applies. Reference designators on D*, R*, and H* are hidden on
silkscreen (57 parts per lens area makes them unreadable; they remain on F.Fab
for assembly).

**Assembly cost is the real difference** — 114 placements versus 72. If you are
paying for turnkey assembly, this variant is roughly 60% more per board, though
both are now single-sided.

## Files

| File | |
|---|---|
| `signal-head-dense.kicad_pro` | project |
| `signal-head-dense.kicad_sch` | schematic, 119 symbols |
| `signal-head-dense.kicad_pcb` | board, placed and netted |
| `bom.csv` | grouped bill of materials |
| `top.png` / `bottom.png` | renders |
| `erc.rpt` / `drc.json` | verification output |
