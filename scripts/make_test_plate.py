#!/usr/bin/env python3
"""make_test_plate.py — generate the standard regression fixture for remodel.py.

Replaces the old dependency on bambu-studio-ai/scripts/parametric.py so the
regression suite in SKILL.md is reproducible from this repo alone.

Typical:
  python3 scripts/make_test_plate.py -o plate.stl
  python3 scripts/make_test_plate.py --width 60 --depth 40 --thickness 4 \
      --holes 4 --hole-diameter 3.2 --hole-spacing-x 25 -o plate.stl

Fixture spec (defaults): 60x40x4 plate with 4 x M3.2 (dia 3.2) through holes
in a 2x2 grid (x spacing 25, y spacing 20), base at origin.
"""
import argparse

import numpy as np

try:
    import manifold3d as m3d
except ImportError:
    raise SystemExit("ERROR: pip install manifold3d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=float, default=60.0)
    ap.add_argument("--depth", type=float, default=40.0)
    ap.add_argument("--thickness", type=float, default=4.0)
    ap.add_argument("--holes", type=int, default=4, choices=[0, 4])
    ap.add_argument("--hole-diameter", type=float, default=3.2)
    ap.add_argument("--hole-spacing-x", type=float, default=25.0)
    ap.add_argument("--hole-spacing-y", type=float, default=20.0)
    ap.add_argument("-o", "--output", default="plate.stl")
    args = ap.parse_args()

    plate = m3d.Manifold.cube([args.width, args.depth, args.thickness])
    if args.holes:
        r = args.hole_diameter / 2.0
        sx = args.hole_spacing_x / 2.0
        sy = args.hole_spacing_y / 2.0
        cx, cy = args.width / 2.0, args.depth / 2.0
        drill = m3d.Manifold.cylinder(args.thickness * 3, r, r, circular_segments=64)
        for dx in (-sx, sx):
            for dy in (-sy, sy):
                plate -= drill.translate([cx + dx, cy + dy, -args.thickness])

    import trimesh
    mm = plate.to_mesh()
    tm = trimesh.Trimesh(
        vertices=np.asarray(mm.vert_properties[:, :3], dtype=np.float64),
        faces=np.asarray(mm.tri_verts, dtype=np.int64),
        process=False,
    )
    tm.export(args.output)
    print(f"wrote {args.output}: {args.width}x{args.depth}x{args.thickness}, "
          f"{args.holes} holes dia {args.hole_diameter}")


if __name__ == "__main__":
    main()