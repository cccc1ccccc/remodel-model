#!/usr/bin/env python3
"""render_stl.py — 2-view PNG render of an STL for chat delivery (WSL-safe).

Why this exists: no Blender/OrcaSlicer/vision-model required — matplotlib
painter's algorithm + Lambert shading. Proven 2026-09-03 (cradle case).

Usage:
    python3 scripts/render_stl.py part.stl -o /mnt/d/part.png \
        --t1 "正视 · 250×15×120 mm" --t2 "俯视 · 6 道肋" --footer "SKÅDIS 摇篮"

Pitfalls baked in (each one bit us once):
- DejaVu Sans has ZERO CJK glyphs → all Chinese renders as boxes. Fix: register
  a Windows font via /mnt/c (msyh.ttc → simhei.ttf fallback chain) and set
  rcParams BEFORE creating the figure.
- Painter's algorithm: sort faces by mean-vertex depth along the view dir,
  draw far-first, else faces bleed through each other.
- ylim is set REVERSED (bmax→bmin) to keep +Y toward the viewer — matches how
  the proven render looked; don't "fix" it.
- RGBA output is fine for Feishu MEDIA delivery (1920×960 at dpi=150).

QA without a vision model (pixel sampling via PIL):
- background pixel == fig facecolor (#101318); object band has thousands of
  lit pixels; footer strip has text pixels.
- text rows = many SHORT bright runs per row; object rows = few WIDE runs.
- matplotlib pixel y is TOP-DOWN in the saved PNG while figure coords are
  BOTTOM-UP — the title strip sits at LOW pixel-row numbers (y≈40-70), not
  high ones. First-sampling attempts that assumed top=high found "0 text px".
"""
import argparse

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--t1", default=None, help="left panel title (CJK ok)")
    ap.add_argument("--t2", default=None, help="right panel title")
    ap.add_argument("--footer", default="")
    ap.add_argument("--elev1", type=int, default=18)
    ap.add_argument("--azim1", type=int, default=-68)
    ap.add_argument("--elev2", type=int, default=62)
    ap.add_argument("--azim2", type=int, default=-50)
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    for f in ("/mnt/c/Windows/Fonts/msyh.ttc", "/mnt/c/Windows/Fonts/simhei.ttf"):
        try:
            fm.fontManager.addfont(f)
            import matplotlib.pyplot as plt
            plt.rcParams["font.family"] = fm.FontProperties(fname=f).get_name()
            break
        except Exception:
            continue
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import trimesh

    m = trimesh.load_mesh(args.stl, process=True)
    m.merge_vertices()
    tris = np.asarray(m.triangles)

    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= (np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12)
    light = np.array([0.45, -0.55, 0.7])
    light /= np.linalg.norm(light)
    shade = 0.25 + 0.75 * np.clip(normals @ light, 0, 1)
    base = np.array([0.960, 0.940, 0.880])
    cols = np.clip(base[None, :] * shade[:, None], 0, 1)

    def render(ax, view_dir, elev, azim, title):
        depth = tris.mean(axis=1) @ view_dir
        order = np.argsort(depth)  # far faces first (painter's algorithm)
        ax.add_collection3d(Poly3DCollection(
            tris[order], facecolors=cols[order], edgecolors="none"))
        ax.set_facecolor("#101318")
        bmin, bmax = m.bounds
        pad = (bmax - bmin).max() * 0.08 + 5
        ax.set_xlim(bmin[0] - pad, bmax[0] + pad)
        ax.set_ylim(bmax[1] + pad, bmin[1] - pad)  # reversed on purpose
        ax.set_zlim(bmin[2] - pad, bmax[2] + pad)
        ax.set_box_aspect((bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2]))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        if title:
            ax.set_title(title, color="#e8e8e8", fontsize=13, pad=2)

    fig = plt.figure(figsize=(12.8, 6.4), facecolor="#101318")
    ax1 = fig.add_axes([0.01, 0.10, 0.48, 0.82], projection="3d")
    render(ax1, np.array([0.5, 1.0, 0.35]), args.elev1, args.azim1,
           args.t1 or f"view 1 · {args.stl}")
    ax2 = fig.add_axes([0.51, 0.10, 0.48, 0.82], projection="3d")
    render(ax2, np.array([0.3, 0.2, 1.0]), args.elev2, args.azim2,
           args.t2 or "view 2")
    if args.footer:
        fig.text(0.5, 0.02, args.footer, ha="center", color="#9aa4b0", fontsize=10)
    fig.savefig(args.out, dpi=150, facecolor="#101318")
    print(f"rendered {len(tris)} tris -> {args.out}")


if __name__ == "__main__":
    main()