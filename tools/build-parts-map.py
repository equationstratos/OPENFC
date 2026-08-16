#!/usr/bin/env python3
"""
Build assets/openfc-visualizer/parts-map.json

The GLB that the visualiser loads (`fc-parts.glb`) has lost every reference
designator: the KiCad -> STEP -> glTF pipeline renamed all 288 solids to
`empty_2` ... `empty_289`. Without a map, the guide cannot know which mesh is
the MCU and which is a 0201 capacitor -- which is why the first version of the
viewer just sliced the mesh list into seven arbitrary chunks.

The reference designators *do* still exist, in the original KiCad STEP export.
This script recovers them and writes a stable mesh-name -> refdes map.

How it works
------------
1. Parse `OpenFC-composants.step`. KiCad emits one
   NEXT_ASSEMBLY_USAGE_OCCURRENCE per placed component, carrying the refdes
   ("U2", "C17", ...) and pointing at the footprint PRODUCT and at an
   ITEM_DEFINED_TRANSFORMATION that holds the placement (x, y, z) and the
   Z axis direction (negative Z => component is on the back face).
2. Parse the GLB JSON chunk of `fc-parts.glb` and take each solid's bounding
   box from the POSITION accessor min/max.
3. The glTF node order is the same as the STEP occurrence order, but a single
   component can span several solids (a connector housing plus its contacts
   plus its moulded-in text). Recover the split with a dynamic program that
   cuts the 288-solid sequence into 111 contiguous segments, minimising the
   total distance between each solid and its component's placement. This is
   exact rather than greedy, so one badly-placed solid cannot derail the rest.
4. Group components into the build steps used by the guide.

Inputs are not kept in the repository (the STEP export is ~20 MB). Recover
them from git history with:

    git cat-file -p d2745990bb7a16241ded8e6f10334ca7f610735f > OpenFC-composants.step
    git cat-file -p 8e2cb7b62ae23709e0e3d8af9c7b7d7048556ab7 > OpenFC-board.step

Usage:
    python3 tools/build-parts-map.py OpenFC-composants.step OpenFC-board.step
"""

import json
import math
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GLB = REPO / "assets/openfc-visualizer/fc-parts.glb"
OUT = REPO / "assets/openfc-visualizer/parts-map.json"


# --------------------------------------------------------------------------
# STEP parsing
# --------------------------------------------------------------------------

def load_step(path):
    body = Path(path).read_text(errors="replace").split("DATA;", 1)[1]
    return {
        int(m.group(1)): " ".join(m.group(2).split())
        for m in re.finditer(r"#(\d+)\s*=\s*(.*?);", body, re.S)
    }


def entity(value):
    return value[: value.index("(")].strip() if "(" in value else ""


def fields(value):
    """Split the top-level comma-separated arguments of `NAME(a,b,(c,d))`."""
    depth, cur, out = 0, "", []
    for ch in value[value.index("(") :]:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                out.append(cur.strip())
                break
        if depth == 1 and ch == ",":
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out


def ident(value):
    return int(str(value).strip().lstrip("#"))


def components(ents):
    """Every placed component: refdes, footprint, placement, face."""

    def triple(ref):
        return [float(v) for v in fields(ents[ref])[1].strip("() ").split(",")]

    def footprint(product_definition):
        formation = ident(fields(ents[product_definition])[2])
        product = ident(fields(ents[formation])[2])
        return fields(ents[product])[0].strip("'")

    out = []
    for value in ents.values():
        if entity(value) != "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION":
            continue
        rel, shape = (ident(f) for f in fields(value)[:2])
        transform = ident(
            re.search(
                r"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION\(\s*#(\d+)", ents[rel]
            ).group(1)
        )
        occurrence = fields(ents[ident(fields(ents[shape])[2])])
        refdes = occurrence[1].strip("'")
        if refdes.startswith("=>"):  # internal sub-assembly link, not a component
            continue
        axis = fields(ents[ident(fields(ents[transform])[3])])
        location = triple(ident(axis[1]))
        z_axis = triple(ident(axis[2])) if len(axis) > 2 and axis[2] != "$" else [0, 0, 1]
        out.append(
            {
                "order": int(occurrence[0].strip("'")),
                "ref": refdes,
                "fp": footprint(ident(occurrence[4])),
                "x": round(location[0], 4),
                "y": round(location[1], 4),
                "z": round(location[2], 4),
                "back": z_axis[2] < 0,
            }
        )
    out.sort(key=lambda c: c["order"])
    return out


def board_facts(path):
    """Outline, thickness and the mounting-hole pattern, straight from the STEP."""
    ents = load_step(path)
    points = {}
    for key, value in ents.items():
        m = re.match(r"CARTESIAN_POINT\('',\(([^)]*)\)\)", value)
        if m:
            points[key] = [float(v) for v in m.group(1).split(",")]

    holes = {}
    for value in ents.values():
        m = re.match(r"CIRCLE\('',#(\d+),([0-9.]+)\)", value)
        if not m:
            continue
        placement = ents[int(m.group(1))]
        centre = points[ident(re.match(r"AXIS2_PLACEMENT_3D\('',#(\d+)", placement).group(1))]
        holes.setdefault(round(float(m.group(2)), 3), set()).add(
            (round(centre[0], 2), round(centre[1], 2))
        )

    mounting = max(holes)  # the Ø4 mm mounting holes are the largest circles
    centres = sorted(holes[mounting])
    xs = sorted({c[0] for c in centres})
    ys = sorted({c[1] for c in centres})
    return {
        "thickness_mm": round(max(p[2] for p in points.values()), 4),
        "mounting_hole_dia_mm": round(mounting * 2, 2),
        "mounting_pitch_mm": [round(xs[-1] - xs[0], 2), round(ys[-1] - ys[0], 2)],
        "mounting_holes": centres,
    }


# --------------------------------------------------------------------------
# GLB parsing
# --------------------------------------------------------------------------

def glb_solids(path):
    """Bounding box (in mm) of every mesh, in glTF node order."""
    data = Path(path).read_bytes()
    total = struct.unpack("<I", data[8:12])[0]
    offset, gltf = 12, None
    while offset < total:
        length = struct.unpack("<I", data[offset : offset + 4])[0]
        if data[offset + 4 : offset + 8] == b"JSON":
            gltf = json.loads(data[offset + 8 : offset + 8 + length])
            break
        offset += 8 + length

    accessors, meshes = gltf["accessors"], gltf["meshes"]
    out = []
    for node in gltf["nodes"]:
        lo, hi = [1e9] * 3, [-1e9] * 3
        for primitive in meshes[node["mesh"]]["primitives"]:
            accessor = accessors[primitive["attributes"]["POSITION"]]
            for axis in range(3):
                lo[axis] = min(lo[axis], accessor["min"][axis])
                hi[axis] = max(hi[axis], accessor["max"][axis])
        # the glTF is in metres, everything else here is in millimetres
        out.append(
            {
                "name": node["name"],
                "min": [v * 1000 for v in lo],
                "max": [v * 1000 for v in hi],
            }
        )
    return out


# --------------------------------------------------------------------------
# Solid -> component
# --------------------------------------------------------------------------

def segment(solids, comps):
    """
    Cut the solid sequence into one contiguous, non-empty run per component,
    minimising the total solid-to-placement distance. Exact, via DP.
    """
    n, m = len(solids), len(comps)
    if n < m:
        raise SystemExit(f"{n} solids for {m} components -- the GLB and STEP disagree")

    cost = []
    for s in solids:
        cx = (s["min"][0] + s["max"][0]) / 2
        cy = (s["min"][1] + s["max"][1]) / 2
        cz = (s["min"][2] + s["max"][2]) / 2
        row = []
        for c in comps:
            # a solid on the wrong face is almost certainly the wrong component
            penalty = 0.0 if ((cz < 0.47) == c["back"]) else 40.0
            row.append(math.hypot(cx - c["x"], cy - c["y"]) + penalty)
        cost.append(row)

    INF = float("inf")
    best = [[INF] * (n + 1) for _ in range(m + 1)]
    back = [[-1] * (n + 1) for _ in range(m + 1)]
    best[0][0] = 0.0
    for j in range(1, m + 1):
        for i in range(j, n - (m - j) + 1):
            run, top, cut = 0.0, INF, -1
            for k in range(i - 1, j - 2, -1):
                run += cost[k][j - 1]
                if best[j - 1][k] + run < top:
                    top, cut = best[j - 1][k] + run, k
            best[j][i], back[j][i] = top, cut

    i = n
    for j in range(m, 0, -1):
        k = back[j][i]
        comps[j - 1]["meshes"] = roles(solids[k:i])
        comps[j - 1]["bb"] = [
            [round(min(s["min"][a] for s in solids[k:i]), 3) for a in range(3)],
            [round(max(s["max"][a] for s in solids[k:i]), 3) for a in range(3)],
        ]
        i = k
    return best[m][n]


def roles(group):
    """
    Label each solid of one component so the viewer can paint it like the real
    part: an epoxy body and its tinned leads are not the same colour.

    KiCad's own colours cannot tell them apart -- it paints almost everything
    the same flat grey -- but the geometry can. The package body is by far the
    largest solid; leads and contacts are small; and moulded-in markings are
    exported as zero-thickness sheets on the surface of the housing.
    """
    volume = lambda s: max(
        (s["max"][0] - s["min"][0]) * (s["max"][1] - s["min"][1]) * (s["max"][2] - s["min"][2]),
        0.0,
    )
    thinnest = lambda s: min(s["max"][a] - s["min"][a] for a in range(3))

    body = max(group, key=volume)
    out = {}
    for s in group:
        if s is body:
            role = "body"
        elif thinnest(s) < 0.02:
            role = "mark"
        elif volume(s) >= 0.45 * volume(body):
            # a second solid nearly as big as the body is a separate part of the
            # same component -- the steel cage over the microSD's plastic frame
            role = "shell"
        else:
            role = "lead"
        out[s["name"]] = role
    return out


# --------------------------------------------------------------------------
# Component -> build step
# --------------------------------------------------------------------------

# The parts that define each step. Everything else is a passive, and gets
# attached to whichever of these it was laid out next to -- which is also the
# rule the board designer followed: a decoupling capacitor belongs to the chip
# it is squeezed against.
ANCHORS = {
    "rails": ["U6", "U16", "L2", "L3", "D4", "D5"],
    "ldo": ["U7", "U15"],
    "mcu": ["U2"],
    "coresmps": ["L1", "C19", "C20", "R10", "R11"],
    "clock": ["X1", "C8", "C11"],
    "imu": ["U9"],
    "boot": ["U1"],
    # D/R pairs: each LED sits in line with its own series resistor
    "status": ["D1", "D7", "D9", "R16", "R28", "R39"],
    "sense": ["U10", "U11", "U12", "D8"],
    # R3/R4 are the 5.1 k CC pull-downs, 3 mm from the receptacle
    "usb": ["USB1", "R3", "R4"],
    "sd": ["Card1"],
    # U5/D2/D3 sit on the exposed connector lines, i.e. ESD protection
    "ports": ["P1", "U8", "U14", "U13", "CN1", "U5", "D2", "D3"],
}

# A hollow shell (the microSD cage, the USB receptacle) has a huge bounding box
# that other components sit inside without belonging to it. Never let those
# claim a neighbour by proximity alone.
SHELLS = {"Card1", "USB1", "P1", "U8", "U14", "U13", "CN1"}


def assign_steps(comps):
    by_ref = {c["ref"]: c for c in comps}
    step_of = {ref: step for step, refs in ANCHORS.items() for ref in refs}
    for ref in step_of:
        if ref not in by_ref:
            raise SystemExit(f"anchor {ref} is not on this board")

    mcu = by_ref["U2"]

    def under_mcu(c):
        return (
            mcu["bb"][0][0] <= c["x"] <= mcu["bb"][1][0]
            and mcu["bb"][0][1] <= c["y"] <= mcu["bb"][1][1]
        )

    def box_distance(c, anchor):
        d = 0.0
        for axis, value in ((0, c["x"]), (1, c["y"])):
            lo, hi = anchor["bb"][0][axis], anchor["bb"][1][axis]
            d += max(lo - value, 0.0, value - hi) ** 2
        # crossing the board costs a little, but a capacitor via-stitched to the
        # pad directly above it is still that pad's capacitor
        return math.sqrt(d) + (0.0 if c["back"] == anchor["back"] else 1.5)

    for c in comps:
        if c["ref"] in step_of:
            c["step"], c["anchor"] = step_of[c["ref"]], True
            continue
        c["anchor"] = False
        # nothing is laid out under a QFN-80 except that QFN's own support parts
        if under_mcu(c):
            c["step"], c["via"] = "mcu", "U2"
            continue
        candidates = [
            (box_distance(c, by_ref[ref]), ref, step)
            for ref, step in step_of.items()
            if ref not in SHELLS or box_distance(c, by_ref[ref]) < 1.2
        ]
        distance, ref, step = min(candidates)
        c["step"], c["via"] = step, ref
    return comps


# --------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__.strip().splitlines()[-1])
    comps_step, board_step = sys.argv[1], sys.argv[2]

    comps = components(load_step(comps_step))
    solids = glb_solids(GLB)
    residual = segment(solids, comps)
    assign_steps(comps)

    for c in comps:
        c.pop("order", None)

    payload = {
        "_comment": (
            "Generated by tools/build-parts-map.py -- do not edit by hand. "
            "Reference designators and placements come from the KiCad STEP "
            "export; mesh names are the glTF nodes of fc-parts.glb."
        ),
        "units": "mm",
        "board": board_facts(board_step),
        "components": comps,
    }
    OUT.write_text(json.dumps(payload, indent=1) + "\n")

    faces = sum(1 for c in comps if c["back"])
    print(f"{len(comps)} components, {len(solids)} solids, residual {residual:.1f} mm")
    print(f"  front face {len(comps) - faces}, back face {faces}")
    print(f"  wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
