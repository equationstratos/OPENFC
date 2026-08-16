# OpenFC board review and build-guide audit

This document answers one question: **does the guide describe the board that is
actually in this repository?** Everything below comes from the exported KiCad
model, not from an assumption about what a flight controller usually carries.

## Where the numbers come from

The viewer loads two glTF files (`fc-board.glb`, `fc-parts.glb`) whose
STEP-to-glTF conversion **erased every reference designator**: all 288 solids are
named `empty_2` … `empty_289`. That is the direct cause of the original problem —
with no designators, the old code sliced the mesh list into seven arbitrary
chunks and therefore "installed" parts at random on every step.

The designators still exist in the original KiCad STEP export, which was deleted
from the repository but survives in git history:

```sh
git cat-file -p d2745990bb7a16241ded8e6f10334ca7f610735f > OpenFC-composants.step
git cat-file -p 8e2cb7b62ae23709e0e3d8af9c7b7d7048556ab7 > OpenFC-board.step
python3 tools/build-parts-map.py OpenFC-composants.step OpenFC-board.step
```

`tools/build-parts-map.py` extracts the 111 placed components (designator,
footprint, position, side) and maps them back onto the 288 glTF solids. The
result is `assets/openfc-visualizer/parts-map.json`, which the guide consumes.

## What this board actually is

| | |
|---|---|
| Outline | 37.94 × 37.94 mm |
| Thickness | 0.938 mm |
| Mounting | 4 × **Ø4.0 mm** holes on a **30.5 × 30.5 mm** pattern |
| Placed components | **111** — 39 front side, 72 back side |

The 30.5 × 30.5 pattern with Ø4 holes is the standard for 5-inch and larger
quads, with M3 soft-mounts. It is the most identifying fact about the board, and
it is verified geometrically.

### The components that carry a function

| Ref | Footprint | Side | Role |
|---|---|---|---|
| U2 | QFN-80 10.0 × 10.0 mm, 0.40 pitch, 3.4 mm pad | front | Microcontroller. The package matches the RP2350B / **RP2354B** exactly |
| U9 | LGA-14 3.0 × 2.5 mm, 0.50 pitch | front | Inertial sensor. The **BMI270** package |
| X1 | 4-pad crystal 2.5 × 2.0 mm | back | Time reference, mounted **directly under** U2 |
| L1 | 2.0 × 1.6 mm inductor (3.3 µH) | front | Core supply — the RP2350's internal switcher requires this external coil |
| U6, U16 | SOT-23-6 2.9 × 1.6 mm | back | Two step-down converters |
| L2, L3 | Shielded inductors 3.0 × 3.0 × 2.0 mm | back | The coils for those two converters |
| U7, U15 | WSON-6 2 × 2 mm | back / front | Linear regulators. U15 sits against U9 |
| U1 | 4-pin SMD switch | front | BOOT button |
| U5, D2, D3 | SOT-583-8, 2 × SOD-882 | back | I/O line protection |
| U10, U11, U12, D8 | X2SON-6, SOT-23-5, X2SON-4, DFN0603 | back | Analog service block |
| Q1, Q2 | DFN-3L 1.0 × 0.6 mm | front / back | Transistors |
| D1, D4, D5, D7, D9 | 0402 LEDs | front | Indicators, each with its series resistor |
| Card1 | TF-SMD push-push, 15.2 × 16.2 mm | back | microSD socket |
| USB1 | USB-C, 16 contacts | back | Programming and power |
| P1 / U14, U8 / CN1 / U13 | JST-SH 1.00 mm — 8P / 2 × 6P / 4P / 3P | back | Connectivity |

The remaining 84 resistors and capacitors (0201, 0402, 0603, 0805) are attached,
in the guide, to whichever component they are placed against — which is also the
rule the layout followed.

## Corrections made to the guide

### 1. Two steps described components that are not there

The old guide had a **"Video/OSD — OSD Chip"** step and a **"Radio —
ExpressLRS"** step. Neither corresponds to anything on the board: the bill of
materials contains no video overlay chip (AT7456E / MAX7456 class) and no radio
transceiver. The only ICs larger than 3 mm are U2 and U9.

On an RP2350-based board the OSD is generated **in software** on the
microcontroller, and the ExpressLRS receiver is an **external module** that plugs
into one of the JST-SH ports. Both steps were replaced with what the board really
carries.

### 2. Also absent, and the guide now says so

No barometer and no current sensor: no footprint in the bill of materials matches
either. That is useful to know before wiring the board up.

### 3. Step order

The new order follows board bring-up rather than chance: supplies → the
microcontroller and its support → clock → sensor → human interface →
connectivity. The final step states explicitly that this breakdown is
**pedagogical**: in production a board is built side by side (stencil, place,
reflow), not function by function.

## Corrections made to the viewer

| Reported problem | Cause | Fix |
|---|---|---|
| You cannot tell which part is being installed | Meshes were sliced into 7 arbitrary chunks unrelated to the components | Each step lights the meshes of the components it actually names, via `parts-map.json` |
| Highlighting unreadable | Every part was permanently visible (`o.visible = true` was forced) | Three states: installed, being placed (highlighted + outline + label), not yet placed (hidden) |
| Board does not turn when parts are on the other side | No notion of side | Each step computes its front/back split and turns the board over on its own; the side badge shows which face you are on |
| "Flip" makes the board disappear | The rotation applied to a group whose origin had been displaced by `ROOT.position.sub(centre)`, so the board swung through an arc about a point outside itself | Split into a pivot at the PCB's geometric centre and a child carrying the recentring and scale. The board now turns on itself |
| Parts do not look real | KiCad exports flat colour — `metalness 0`, `roughness 1`, and the same grey for a ceramic capacitor, a steel shield and an epoxy package | Materials are chosen per footprint class and per solid role (see below) |

### Component colours

`build-parts-map.py` labels every solid of a component as `body`, `lead`,
`shell` or `mark`. KiCad's own colours cannot tell those apart, but the geometry
can: the package body is by far the largest solid, leads and contacts are small,
and moulded-in lettering is exported as zero-thickness sheets on the housing
surface. The viewer then pairs that role with the footprint name to pick a
material:

| Class | Body | Leads |
|---|---|---|
| `C_0201…0805` | pale tan ceramic | tinned |
| `R_0201` | dark thick-film top | tinned |
| `LED_0402` | phosphor ivory, faint glow | tinned |
| `IND-SMD` | matte iron-powder composite | tinned |
| `CRYSTAL-SMD` | nickel-plated lid | tinned |
| `TF-SMD` (microSD) | black plastic frame | stainless cage (`shell`) |
| `USB-TYPE-C` | stainless shell | — |
| `CONN-SMD` (JST-SH) | natural nylon | gold-flashed contacts |
| `SW-SMD`, QFN, LGA, SOT, WSON, DFN | black epoxy | tinned |

The laminate renders flat-shaded, because KiCad's smoothed normals ripple across
what is a dead-flat surface.

An **X-ray** mode makes the PCB translucent, and switches itself on when a step
genuinely spans both sides.
