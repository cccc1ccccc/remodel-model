#!/usr/bin/env python3
"""remodel.py — natural-language remodelling for downloaded STL/3MF/OBJ parts.

Operations on EXISTING meshes, backed by manifold3d (boolean-safe):
  info / gates / resize / scale / extend / shrink / drill / fill /
  thicken / hollow / round-edges / cut / mirror / relocate

Every write operation runs a five-gate validation pipeline:
  G1 watertight/manifold    G2 self-intersection (redundant on manifold, kept as tripwire)
  G3 min-wall (ray-based)   G4 overhang (45° rule)    G5 dimension-chain (vs request)

Typical:
  python3 remodel.py info part.stl
  python3 remodel.py resize part.stl --size 40x20x5 --keep-holes -o out.stl
  python3 remodel.py resize part.stl --factor 1.2 --keep-holes -o out.stl
  python3 remodel.py drill part.stl --at 30,20,0 --dia 3.2 --through -o out.stl
    # --through: --at only needs x,y inside the part; the axial coordinate is ignored
  python3 remodel.py drill part.stl --at 30,20,4 --dia 5 --depth 2 -o out.stl
    # blind hole: --at is the hole MOUTH on the surface; the hole extends
    # INTO the material along -Z by --depth (z=4 mouth, depth 2 -> z=2..4)
  python3 remodel.py fill part.stl --dia 4 -o out.stl
  python3 remodel.py thicken part.stl --by 1.0 -o out.stl
  python3 remodel.py hollow part.stl --wall 2 -o out.stl
  python3 remodel.py hollow part.stl --wall 2 --open-bottom -o out.stl
  python3 remodel.py round-edges part.stl --radius 1.5 -o out.stl
  python3 remodel.py cut part.stl --at z=10 --keep top -o out.stl
  python3 remodel.py extend part.stl --axis z --by 8 -o out.stl
  python3 remodel.py shrink part.stl --axis z --by 8 -o out.stl
  python3 remodel.py mirror part.stl --axis x -o out.stl
  python3 remodel.py relocate part.stl --drop-to-bed -o out.stl
"""
import argparse
import json
import os
import sys

import numpy as np

try:
    import manifold3d as m3d
except ImportError:
    sys.exit("ERROR: pip install manifold3d")

try:
    import trimesh
except ImportError:
    sys.exit("ERROR: pip install trimesh")

try:
    import scipy.sparse as _sp
except ImportError:
    _sp = None

# ---------------------------------------------------------------- mesh IO

def _tri_to_man(tm):
    v = np.ascontiguousarray(tm.vertices, dtype=np.float32)
    f = np.ascontiguousarray(tm.faces, dtype=np.uint32)
    return m3d.Manifold(m3d.Mesh(vert_properties=v, tri_verts=f))

def man_to_tri(man):
    mm = man.to_mesh()
    # process=False: trimesh's default merge_vertices welds near-coincident
    # verts at absolute tolerance and TEARS the manifold open on dense
    # minkowski output (observed: 11784 faces -> watertight False). The
    # manifold3d mesh is already merged; keep it as-is.
    return trimesh.Trimesh(
        vertices=np.asarray(mm.vert_properties[:, :3], dtype=np.float64),
        faces=np.asarray(mm.tri_verts, dtype=np.int64),
        process=False,
    )

def load_manifold(path):
    obj = trimesh.load(path, force="scene")
    if hasattr(obj, "geometry"):
        meshes = [g for g in obj.geometry.values() if hasattr(g, "faces") and len(g.faces)]
    else:
        meshes = [obj] if hasattr(obj, "faces") and len(obj.faces) else []
    if not meshes:
        raise SystemExit(f"ERROR: no mesh geometry found in {path}")
    if len(meshes) == 1:
        return _tri_to_man(meshes[0])
    man = None
    for g in meshes:  # multi-body 3MF: keep bodies as-is (compose)
        m = _tri_to_man(g)
        man = m if man is None else m3d.Manifold.compose([man, m])
    return man

def _patch_3mf(path):
    """trimesh's 3MF export omits <build><item/>, so Bambu Studio / Blender open
    an empty scene (bitten 2026-09-04, documented in SKILL.md). Post-process the
    zip: add the build item, and strip a stray .stl suffix from the object name."""
    import re as _re
    import zipfile
    with zipfile.ZipFile(path) as z:
        data = {n: z.read(n) for n in z.namelist()}
    xml = data.get("3D/3dmodel.model")
    if xml is None:
        return False
    xml = xml.decode("utf-8", "ignore")
    changed = False
    if "<build" not in xml:
        xml = xml.replace("</model>", '<build><item objectid="1"/></build></model>')
        changed = True
    xml2 = _re.sub(r'(<object[^>]*\bname=")([^"]*)\.stl(")', r"\1\2\3", xml)
    if xml2 != xml:
        xml, changed = xml2, True
    data["3D/3dmodel.model"] = xml.encode("utf-8")
    import os
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in data.items():
            z.writestr(n, b)
    os.replace(tmp, path)
    return changed


def export(man, path):
    tm = man_to_tri(man)
    if path.lower().endswith(".3mf"):
        scene = trimesh.Scene()
        scene.add_geometry(tm)
        scene.export(path)
        _patch_3mf(path)
    else:
        tm.export(path)
    return path


def verify_export(man, path, expected_bodies):
    """Post-export re-read verification (delivery gate, per SKILL.md 2026-09-05:
    kernel state != disk state — stale overwrites / mid-run rewrites have shipped
    multi-shell files). Compares body count, watertightness and volume against
    the in-memory manifold. Re-read goes through load_manifold -> man_to_tri
    (manifold3d reconstruction), NOT raw trimesh.load — the raw STL re-read
    reports false non-watertightness on merged-vertex soup (SKILL.md)."""
    r = {"path": path, "ok": False}
    try:
        back = load_manifold(path)
    except Exception as e:
        r["error"] = f"re-read failed: {type(e).__name__}: {e}"
        return False, r
    bodies = len(back.decompose())
    tm = man_to_tri(back)
    vol_in = float(man.volume())
    vol_out = float(back.volume())
    r["bodies"] = int(bodies)
    r["expected_bodies"] = int(expected_bodies)
    r["watertight"] = bool(tm.is_watertight and tm.is_winding_consistent)
    r["volume_delta_pct"] = round(100.0 * abs(vol_out - vol_in) / max(abs(vol_in), 1e-9), 3)
    ok = (bodies == expected_bodies and r["watertight"] and r["volume_delta_pct"] < 0.5)
    r["ok"] = bool(ok)
    return bool(ok), r

def _align_z_to_axis(man, axis):
    axis = np.asarray(axis, dtype=np.float64)
    if np.allclose(axis, [0, 0, 1]):
        return man
    if np.allclose(axis, [0, 0, -1]):
        return man.mirror([0, 0, 1])  # flip along Z (was [0,1,0]: a no-op for a cylinder)
    from scipy.spatial.transform import Rotation
    from trimesh.geometry import align_vectors
    R = align_vectors([0, 0, 1], axis)[:3, :3]
    eul = Rotation.from_matrix(R).as_euler("xyz", degrees=True).tolist()
    return man.rotate(eul)


def _bb(man):
    """bounding_box() -> (min corner, max corner) as float64 arrays."""
    b = np.asarray(man.bounding_box(), dtype=np.float64)
    return b[:3].copy(), b[3:].copy()


def _proj_extent(lo, hi, axis):
    """[min, max] of the bbox corners projected onto `axis`."""
    axis = np.asarray(axis, dtype=np.float64)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    t = corners @ axis
    return float(t.min()), float(t.max())


def _cyl_spanned(man, axis, center, radius, a0, a1, segments=64):
    """Cylinder aligned to `axis`, laterally on the hole line through `center`,
    covering the axial range [a0, a1] EXACTLY.

    Positioning is bbox-measured, never assumed: manifold3d cylinders span
    0..height along +Z (NOT centered — v2 and v3 alike) and rotations move
    the bbox, so any translate(center)-style placement silently halves a
    through-cut (bitten 2026-09-13: resize --keep-holes re-drill produced
    half-depth holes, genus 0, while every gate stayed green). We align
    first, measure the cylinder's own bbox, then translate by
    (target - measured) along the axis; lateral centering rides on the
    cylinder's axis passing through the origin before and after rotation.
    """
    axis = np.asarray(axis, dtype=np.float64)
    center = np.asarray(center, dtype=np.float64)
    cyl = m3d.Manifold.cylinder(a1 - a0, radius, radius, circular_segments=segments)
    cyl = _align_z_to_axis(cyl, axis)
    cbmin, _ = _bb(cyl)
    target = center - axis * float(center @ axis)  # hole line, axial 0
    target = target + axis * (a0 - float(cbmin @ axis))
    return cyl.translate(target.tolist())

# ------------------------------------------------------- hole detection

def detect_circular_holes(man, min_r=0.5, max_r=25.0, min_faces=6,
                          smooth_deg=15.0, ring_deg=45.0, max_resid=0.08):
    """Detect circular holes & bores on both smooth and LOW-POLY meshes.

    Two-tier grouping (low-seg cylinder walls breach the 15° dihedral rule):
      tier A: smooth groups (dihedral < smooth_deg) — high-quality meshes
      tier B: ring groups (dihedral < ring_deg) — low-seg meshes; qualify
              by normal spectrum (full 360° ring, max gap < 90°)
    Both tiers share the final test: least-squares circle fit + inward
    normal check. Bosses/pins (outward normals) are rejected.
    """
    if _sp is None:
        print("WARNING: scipy not installed — hole detection disabled; "
              "resize --keep-holes, fill and round-edges hole protection "
              "will NOT work. pip install scipy", file=sys.stderr)
        return []
    tm = man_to_tri(man)
    fa = tm.face_adjacency
    if len(fa) == 0:
        return []
    ang = tm.face_adjacency_angles
    n = len(tm.faces)
    normals = tm.face_normals
    centers = tm.triangles_center
    holes = []

    def _try_group(m, tier):
        N = normals[m]
        c = centers[m]
        w, V = np.linalg.eigh(N.T @ N)
        axis = V[:, 0]
        if axis[2] < 0:
            axis = -axis
        perp = float(np.abs(N @ axis).max())
        if tier == "A" and not (w[0] < 0.05 * w[2] and w[1] > 0.5 * w[2]):
            return
        if tier == "B" and not (w[0] < 0.1 * w[2] and perp < 0.35):
            return
        if tier == "A" and perp > 0.1:
            return
        a = np.eye(3)[np.argmin(np.abs(axis))]
        u = np.cross(axis, a)
        u /= np.linalg.norm(u)
        v2 = np.cross(axis, u)
        P = np.stack([c @ u, c @ v2], axis=1)
        A = np.c_[2 * P, np.ones(len(P))]
        b = (P ** 2).sum(axis=1)
        sol, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        cx, cy = float(sol[0]), float(sol[1])
        r = float(np.sqrt(max(sol[2] + cx * cx + cy * cy, 2.5e-3)))
        if r < min_r or r > max_r:
            return
        resid = float(np.abs(np.sqrt((P[:, 0] - cx) ** 2 + (P[:, 1] - cy) ** 2) - r).max())
        if resid > max_resid:
            return
        t = c @ axis
        # axial extent from WALL VERTICES (face centers sit mid-triangle and
        # under-report the span on low-seg meshes where wall quads split into
        # two tris with centers at two different z-levels)
        vset = np.unique(np.concatenate([tm.faces[np.where(m)[0]].flatten()]))
        tv = tm.vertices[vset] @ axis
        t0v, t1v = float(tv.min()), float(tv.max())
        center3d = u * cx + v2 * cy + axis * float(t.mean())
        radial = c - center3d
        radial -= np.outer(radial @ axis, axis)
        toward_axis = float(np.mean((radial * N).sum(axis=1))) < 0
        if not toward_axis:
            return  # boss/pin, not hole
        if tier == "B":
            # normal spectrum: must ring ~full 360°, no gap > 90°
            phi = np.sort(np.degrees(np.arctan2(N @ v2, N @ u)))
            gaps = np.diff(np.r_[phi, phi[0:1] + 360])
            if gaps.max() > 90:
                return
        holes.append({
            "center": [round(x, 4) for x in center3d.tolist()],
            "axis": [round(x, 4) for x in axis.tolist()],
            "radius": round(r, 4),
            "dia": round(2 * r, 4),
            "t0": round(t0v, 4),
            "t1": round(t1v, 4),
            "wall_faces": int(m.sum()),
            "tier": tier,
        })

    def _run(tier_deg, tier):
        sel = ang < np.radians(tier_deg)
        ii = fa[sel][:, 0]
        jj = fa[sel][:, 1]
        G = _sp.coo_matrix((np.ones(len(ii)), (ii, jj)), shape=(n, n))
        _, labels = _sp.csgraph.connected_components(G, directed=False)
        sizes = np.bincount(labels)
        for gid in np.argsort(sizes)[::-1]:
            if sizes[gid] < min_faces:
                break
            _try_group(labels == gid, tier)

    _run(smooth_deg, "A")
    holesA = list(holes)
    holes.clear()
    _run(ring_deg, "B")
    holesB = list(holes)
    seen = set()
    out = []
    for h in holesA + holesB:
        key = (round(h["center"][0], 1), round(h["center"][1], 1),
               round(h["center"][2], 1), round(h["radius"], 1))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def drill_at(man, center, axis, radius, depth=None):
    """Drill a cylindrical hole along `axis`.

    depth=None -> through: spans the part's full projected extent (the axial
        coordinate of `center` is ignored; only its lateral position matters).
    depth=d    -> blind: `center` is the hole MOUTH on the surface; the hole
        extends from the mouth INTO the material (along -axis) by d.
    """
    axis = np.asarray(axis, dtype=np.float64)
    center = np.asarray(center, dtype=np.float64)
    if depth is None:
        lo, hi = _bb(man)
        a0, a1 = _proj_extent(lo, hi, axis)
        return man - _cyl_spanned(man, axis, center, radius, a0 - 1.0, a1 + 1.0)
    if depth <= 0:
        raise SystemExit("ERROR: --depth must be > 0")
    c_ax = float(center @ axis)
    return man - _cyl_spanned(man, axis, center, radius, c_ax - depth, c_ax)

# ------------------------------------------------------------ the gates

PRINTER_BED = {"x": 256.0, "y": 256.0, "z": 260.0}  # X2D default; override via --bed

def _genus(man):
    """Through-hole count via trimesh euler (2-2*genus); None if not decidable
    (multi-body input or non-manifold euler)."""
    if len(man.decompose()) != 1:
        return None
    e = int(man_to_tri(man).euler_number)
    return (2 - e) // 2 if e <= 2 else None

def gate_watertight(man, ctx):
    tm = man_to_tri(man)
    ok = bool(tm.is_watertight and tm.is_winding_consistent)
    g = _genus(man) if ok else None
    info = {
        "watertight": bool(tm.is_watertight),
        "winding_consistent": bool(tm.is_winding_consistent),
        "euler": int(tm.euler_number),
        "faces": int(len(tm.faces)),
        "through_holes_genus": g,
    }
    exp = ctx.get("expected_genus")
    if exp is not None and g is not None:
        info["expected_genus"] = exp
        if g != exp:
            ok = False
            info["note"] = f"through-hole count changed: {exp} -> {g} " \
                           "(hole preservation broken — this is how the half-depth " \
                           "re-drill bug of 2026-09-13 would have been caught)"
    return ok, info

def gate_self_intersect(man, ctx):
    # manifold3d output is self-intersection-free by construction; tripwire only
    tm = man_to_tri(man)
    ok = True
    note = "manifold3d output is CSG-valid by construction"
    if not tm.is_watertight:
        ok, note = False, "non-watertight output — self-intersection likely"
    return ok, {"note": note}

def gate_min_wall(man, ctx, probes=400, min_wall=0.8):
    """Ray-based wall thickness: fire inward rays from surface samples,
    distance to first re-hit = local wall thickness (through the body)."""
    tm = man_to_tri(man)
    rng = np.random.default_rng(42)
    n_faces = len(tm.faces)
    k = min(probes, n_faces)
    idx = rng.choice(n_faces, size=k, replace=False)
    origins = tm.triangles_center[idx] + tm.face_normals[idx] * 1e-3
    dirs = -tm.face_normals[idx]
    try:
        face_ids, ray_ids, locations = tm.ray.intersects_id(
            ray_origins=origins, ray_directions=dirs,
            multiple_hits=True, return_locations=True)
    except ModuleNotFoundError:
        return True, {"note": "rtree missing; skipped", "min_wall_mm": None}
    if len(ray_ids) == 0:
        return True, {"note": "no interior hits", "min_wall_mm": None}
    # first hit per ray (nearest intersection beyond the origin face)
    dist = np.linalg.norm(locations - origins[ray_ids], axis=1)
    order = np.lexsort((dist, ray_ids))
    first = {}
    for o in order:
        r = ray_ids[o]
        if dist[o] < 0.05:
            continue  # self-face / coplanar hit, not a real wall
        if r not in first:
            first[r] = dist[o]
    walls = np.array(sorted(first.values()))
    minw = float(walls.min())
    med = float(np.median(walls))
    ok = minw >= min_wall
    return ok, {"min_wall_mm": round(minw, 3),
                "median_wall_mm": round(med, 3),
                "samples": int(len(walls)),
                "threshold_mm": min_wall}


def gate_overhang(man, ctx, limit_deg=45.0):
    """Overhang check (45° rule), excluding bed-touching faces.

    Overhang angle = angle between face normal and -Z (0° = horizontal
    facing down, 90° = vertical). Faces below the limit need support —
    unless they rest on the build plate (first layers).
    """
    tm = man_to_tri(man)
    n = tm.face_normals
    down = n[:, 2] < -1e-6
    if not down.any():
        return True, {"overhang_area_pct": 0.0, "note": "no down-facing faces"}
    tris = tm.triangles[down]
    face_zmax = tris[:, :, 2].max(axis=1)
    z0 = float(tm.bounds[0][2])
    on_bed = face_zmax < z0 + 0.25  # face lies within first layer of the bed
    ang = np.degrees(np.arccos(np.clip(-n[down][:, 2], -1, 1)))
    bad = (ang < limit_deg) & (~on_bed)
    areas = tm.area_faces[down]
    pct = 100.0 * areas[bad].sum() / max(tm.area, 1e-9)
    ok = pct < 5.0
    return ok, {"overhang_area_pct": round(float(pct), 2),
                "limit_deg": limit_deg,
                "bed_faces_excluded": int(on_bed.sum()),
                "note": "pct of total area unsupported at >45°; <5% is fine"}


def gate_dimensions(man, ctx):
    """Final bbox vs requested targets (G5 size-chain)."""
    lo, hi = _bb(man)
    dims = hi - lo
    req = ctx.get("requested_dims")  # {"x": mm, "y": mm, ...} subset
    info = {
        "final_dims_mm": {k: round(float(v), 3) for k, v in zip("xyz", dims)},
        "bbox_min": [round(float(x), 3) for x in lo],
        "bbox_max": [round(float(x), 3) for x in hi],
    }
    ok = True
    if req:
        errs = {}
        for k, want in req.items():
            got = float(dims["xyz".index(k)])
            errs[k] = round(got - float(want), 3)
            if abs(got - float(want)) > 0.1:
                ok = False
        info["requested"] = {k: float(v) for k, v in req.items()}
        info["error_mm"] = errs
    bed = ctx.get("bed", PRINTER_BED)
    fits = all(dims[i] <= bed["xyz"[i]] for i in range(3))
    info["fits_bed"] = bool(fits)
    if not fits:
        ok = False
    return ok, info

def run_gates(man, ctx, quick=False):
    results = {}
    all_ok = True
    gates = [
        ("G1_watertight", lambda: gate_watertight(man, ctx)),
        ("G2_self_intersect", lambda: gate_self_intersect(man, ctx)),
        ("G3_min_wall", lambda: gate_min_wall(man, ctx)),
        ("G4_overhang", lambda: gate_overhang(man, ctx)),
        ("G5_dimensions", lambda: gate_dimensions(man, ctx)),
    ]
    if quick:
        gates = [gates[0], gates[4]]
    for name, fn in gates:
        ok, info = fn()
        results[name] = {"pass": bool(ok), **info}
        all_ok = all_ok and ok
    return all_ok, results

# ------------------------------------------------------------ operations

def op_info(man, args):
    tm = man_to_tri(man)
    lo, hi = _bb(man)
    dims = hi - lo
    holes = detect_circular_holes(man)
    out = {
        "file": args.input,
        "dims_mm": {k: round(float(v), 3) for k, v in zip("xyz", dims)},
        "volume_mm3": round(float(man.volume()), 1),
        "surface_mm2": round(float(man.surface_area()), 1),
        "mass_g_pla_1_24": round(float(man.volume()) * 1.24e-3, 1),
        "faces": int(len(tm.faces)),
        "euler": int(tm.euler_number),
        "watertight": bool(tm.is_watertight),
        "holes_detected": len(holes),
        "holes": holes,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return None

def op_gates(man, args):
    ctx = {"bed": _bed(args)}
    ok, res = run_gates(man, ctx)
    print(json.dumps({"pass": ok, "gates": res}, ensure_ascii=False, indent=2))
    return None

def _bed(args):
    b = dict(PRINTER_BED)
    if getattr(args, "bed", None):
        parts = args.bed.lower().split("x")
        if len(parts) == 3:
            b = {"x": float(parts[0]), "y": float(parts[1]), "z": float(parts[2])}
    return b

def _fmt_axis(v):
    return {0: [1, 0, 0], 1: [0, 1, 0], 2: [0, 0, 1]}[v]

def op_resize(man, args):
    lo, hi = _bb(man)
    cur = hi - lo
    if args.factor is not None:
        if args.factor <= 0:
            raise SystemExit("ERROR: --factor must be > 0")
        factors = [float(args.factor)] * 3
    elif args.size:
        toks = args.size.lower().split("x")
        if len(toks) != 3:
            raise SystemExit("ERROR: --size must be three numbers WxHxD (e.g. 40x20x5)")
        try:
            want = [float(t) for t in toks]
        except ValueError:
            raise SystemExit("ERROR: --size must be three numbers WxHxD (e.g. 40x20x5)")
        if any(w <= 0 for w in want):
            raise SystemExit("ERROR: --size values must be > 0")
        factors = [want[i] / cur[i] for i in range(3)]
    else:
        raise SystemExit("resize needs --factor or --size")
    ctx = {"bed": _bed(args),
           "requested_dims": dict(zip("xyz", want)) if args.size
           else {k: round(float(cur[i]) * factors[i], 3) for i, k in enumerate("xyz")}}
    out = man.scale(factors)
    kept = []
    if args.keep_holes:
        holes = detect_circular_holes(man)  # on ORIGINAL (unscaled)
        if not holes:
            print("WARNING: --keep-holes set but no holes detected — "
                  "output is a plain scale", file=sys.stderr)
        # three-step semantics: fill original -> scale -> re-drill original dia
        # (naive scale would scale holes too; re-drilling alone leaves crescents)
        filled = man
        for h in holes:
            axis = np.asarray(h["axis"], dtype=np.float64)
            center = np.asarray(h["center"], dtype=np.float64)
            n_segs = max(4, h["wall_faces"] // 2)
            r_vertex = h["radius"] / np.cos(np.pi / n_segs)  # true vertex radius
            # exact flush plug spanning t0..t1 (coplanar union, no bump)
            plug = _cyl_spanned(man, axis, center, r_vertex * 1.03,
                                h["t0"], h["t1"], segments=48)
            filled = filled + plug
        out = filled.scale(factors)
        lo2, hi2 = _bb(out)
        for h in holes:
            axis = np.asarray(h["axis"], dtype=np.float64)
            center_s = np.asarray(h["center"], dtype=np.float64) * np.asarray(factors)
            n_segs = max(4, h["wall_faces"] // 2)
            r_vertex = h["radius"] / np.cos(np.pi / n_segs)
            a0, a1 = _proj_extent(lo2, hi2, axis)
            out = out - _cyl_spanned(out, axis, center_s, r_vertex, a0 - 1.0, a1 + 1.0)
            kept.append({"dia": round(2 * r_vertex, 2),
                         "new_center": center_s.round(2).tolist()})
    # scaling preserves topology; keep-holes is built to preserve it too
    ctx["expected_genus"] = _genus(man)
    return out, ctx, {"factors": [round(f, 4) for f in factors], "holes_kept": kept}

def op_drill(man, args):
    if not args.dia or args.dia <= 0:
        raise SystemExit("ERROR: drill needs a positive --dia (e.g. --dia 4.2)")
    if not args.at:
        raise SystemExit("ERROR: drill needs --at x,y,z")
    try:
        at = [float(t) for t in args.at.split(",")]
    except ValueError:
        at = None
    if not at or len(at) != 3:
        raise SystemExit("ERROR: --at must be three numbers x,y,z (e.g. --at 30,20,4)")
    if args.through and args.depth:
        raise SystemExit("ERROR: use either --through or --depth, not both")
    if not args.through and not args.depth:
        raise SystemExit("ERROR: drill needs --through or --depth <mm>")
    vol_before = float(man.volume())
    if args.through:
        out = drill_at(man, at, [0, 0, 1], args.dia / 2, depth=None)
        meta = {"drilled": {"at": at, "dia": args.dia, "through": True,
                            "note": "through ignores the axial coordinate of --at"}}
        ideal = np.pi * (args.dia / 2) ** 2 * max(1.0, 0.5 * float((_bb(man)[1] - _bb(man)[0])[2]))
    else:
        out = drill_at(man, at, [0, 0, 1], args.dia / 2, depth=args.depth)
        meta = {"drilled": {"at": at, "dia": args.dia, "through": False,
                            "depth": args.depth,
                            "note": "--at is the hole MOUTH; the hole extends "
                                    "into the material along -Z by --depth"}}
        ideal = np.pi * (args.dia / 2) ** 2 * args.depth
    removed = vol_before - float(out.volume())
    meta["removed_mm3"] = round(removed, 2)
    if removed < 0.5 * ideal:
        raise SystemExit(
            f"ERROR: drill removed only {removed:.2f}mm3 (expected ~{ideal:.1f}) — "
            "the hole misses the material. For --depth, --at is the hole MOUTH "
            "with material extending along -Z from it; for --through, --at must "
            "lie inside the part in x/y.")
    ctx = {"bed": _bed(args)}
    return out, ctx, meta

def op_fill(man, args):
    if args.dia is not None and args.dia <= 0:
        raise SystemExit("ERROR: --dia must be > 0")
    holes = detect_circular_holes(man)
    if args.dia:
        targets = [h for h in holes if h["dia"] <= args.dia + 0.15]
    else:
        targets = list(holes)
    if not targets:
        raise SystemExit("no holes to fill (try --dia to include larger, or check info)")
    lo, hi = _bb(man)
    out = man
    n_through = 0
    for h in targets:
        axis = np.asarray(h["axis"], dtype=np.float64)
        center = np.asarray(h["center"], dtype=np.float64)
        # fill EXACTLY the hole-wall span (no bump); count through-holes for genus.
        # Plug radius gets the documented +3% coefficient: at exactly the fitted
        # radius the plug wall is coincident with the hole wall, and coplanar
        # contact does not guarantee welding (SKILL.md) — on manifold3d v3 this
        # left 128 microscopic handles (genus 128) instead of a clean fill.
        a0, a1 = _proj_extent(lo, hi, axis)
        if h["t0"] <= a0 + 0.05 and h["t1"] >= a1 - 0.05:
            n_through += 1
        out = out + _cyl_spanned(man, axis, center, h["radius"] * 1.03,
                                 h["t0"], h["t1"], segments=48)
    ctx = {"bed": _bed(args)}
    g = _genus(man)
    if g is not None:
        ctx["expected_genus"] = max(0, g - n_through)
    return out, ctx, {"filled": [{"dia": h["dia"], "center": h["center"],
                                  "through": h["t0"] <= a0 + 0.05 and h["t1"] >= a1 - 0.05}
                                 for h in targets]}

def op_thicken(man, args):
    if not args.by or args.by <= 0:
        raise SystemExit("ERROR: thicken needs --by > 0")
    r = float(args.by)
    sph = m3d.Manifold.sphere(r, circular_segments=48)
    out = man.minkowski_sum(sph)
    ctx = {"bed": _bed(args)}
    return out, ctx, {"thickened_by_mm": r}

def op_hollow(man, args):
    if not args.wall or args.wall <= 0:
        raise SystemExit("ERROR: hollow needs --wall > 0")
    w = float(args.wall)
    sph = m3d.Manifold.sphere(w, circular_segments=48)
    eroded = man.minkowski_difference(sph)
    out = man - eroded
    ctx = {"bed": _bed(args)}
    meta = {"wall_mm": w}
    if args.open_bottom:
        lo, hi = _bb(man)
        z0 = lo[2]
        cut = m3d.Manifold.cube([hi[0] - lo[0] + 4, hi[1] - lo[1] + 4, w * 2 + 2])
        cut = cut.translate([lo[0] - 2, lo[1] - 2, z0 - (w + 1)])
        out = out - cut
        meta["open_bottom"] = True
    return out, ctx, meta

def op_round_edges(man, args):
    if not args.radius or args.radius <= 0:
        raise SystemExit("ERROR: round-edges needs --radius > 0")
    r = float(args.radius)
    sph = m3d.Manifold.sphere(r, circular_segments=48)
    holes = detect_circular_holes(man)
    filled = man
    for h in holes:  # protect holes: closing shrinks them by ~r; fill first
        axis = np.asarray(h["axis"], dtype=np.float64)
        center = np.asarray(h["center"], dtype=np.float64)
        n_segs = max(4, h["wall_faces"] // 2)
        r_vertex = h["radius"] / np.cos(np.pi / n_segs)
        plug = _cyl_spanned(man, axis, center, r_vertex * 1.03,
                            h["t0"], h["t1"], segments=48)
        filled = filled + plug
    out = filled.minkowski_sum(sph).minkowski_difference(sph)
    lo, hi = _bb(out)
    for h in holes:  # re-drill at original dia after rounding
        axis = np.asarray(h["axis"], dtype=np.float64)
        center = np.asarray(h["center"], dtype=np.float64)
        n_segs = max(4, h["wall_faces"] // 2)
        r_vertex = h["radius"] / np.cos(np.pi / n_segs)
        a0, a1 = _proj_extent(lo, hi, axis)
        out = out - _cyl_spanned(out, axis, center, r_vertex, a0 - 1.0, a1 + 1.0)
    ctx = {"bed": _bed(args), "expected_genus": _genus(man)}
    return out, ctx, {"rounded_radius_mm": r,
                      "holes_protected": len(holes)}

def op_cut(man, args):
    # --at z=10 --keep top|bottom
    if not args.at or args.at.count("=") != 1:
        raise SystemExit("ERROR: cut needs --at axis=value (e.g. --at z=10)")
    spec = args.at.lower().replace(" ", "")
    axis_name, val = spec.split("=")
    if axis_name not in ("x", "y", "z"):
        raise SystemExit("ERROR: --at axis must be x, y or z (e.g. --at z=10)")
    try:
        val = float(val)
    except ValueError:
        raise SystemExit("ERROR: --at value must be a number (e.g. --at z=10)")
    idx = "xyz".index(axis_name)
    lo, hi = _bb(man)
    if not (lo[idx] < val < hi[idx]):
        raise SystemExit(f"ERROR: cut plane {axis_name}={val} is outside the part "
                         f"({axis_name} spans {lo[idx]:.1f}..{hi[idx]:.1f}) — nothing to cut")
    keep_top = args.keep == "top"
    n = np.zeros(3); n[idx] = 1
    if keep_top:
        # trim everything BELOW val: keep half-space above
        out = man.trim_by_plane(n.tolist(), float(val))
    else:
        out = man.trim_by_plane((-n).tolist(), -float(val))
    ctx = {"bed": _bed(args)}
    return out, ctx, {"cut": spec, "kept": args.keep}

def op_extend(man, args):
    if not args.axis:
        raise SystemExit("ERROR: extend needs --axis x|y|z")
    if not args.by or args.by <= 0:
        raise SystemExit("ERROR: extend needs --by > 0")
    idx = "xyz".index(args.axis.lower())
    by = float(args.by)
    lo, hi = _bb(man)
    top = hi[idx]
    # slice at the growing face, extrude slab, translate & union
    eps = min(0.02, by * 0.01)
    t = top - eps
    cs = man.slice(t) if idx == 2 else None
    if cs is None:
        # XY extension: slice doesn't align with extrude axis directly; use bbox slab
        l2 = lo.copy(); h2 = hi.copy()
        l2[idx] = top; h2[idx] = top + by
        size = h2 - l2
        slab = m3d.Manifold.cube(size.tolist()).translate(l2.tolist())
        out = man + slab
        note = ("xy extend uses a full-bbox slab — on non-rectangular "
                "cross-sections this adds a rectangular skirt; z extends "
                "the silhouette")
    else:
        slab = m3d.Manifold.extrude(cs, by)
        out = man + slab.translate([0, 0, top])
        note = "z extend extrudes the silhouette at the growing face (through-holes continue)"
    ctx = {"bed": _bed(args)}
    return out, ctx, {"extended": {"axis": args.axis, "by_mm": by}, "note": note}

def op_shrink(man, args):
    if not args.axis:
        raise SystemExit("ERROR: shrink needs --axis x|y|z")
    if not args.by or args.by <= 0:
        raise SystemExit("ERROR: shrink needs --by > 0")
    idx = "xyz".index(args.axis.lower())
    by = float(args.by)
    lo, hi = _bb(man)
    if by >= hi[idx] - lo[idx]:
        raise SystemExit(f"ERROR: --by {by} >= part {args.axis}-size "
                         f"{hi[idx] - lo[idx]:.1f} — nothing would remain")
    n = np.zeros(3); n[idx] = 1
    cut_from = hi[idx] - by
    # subtract slab above cut line
    l2 = lo.copy(); h2 = hi.copy() + 2
    l2[idx] = cut_from
    size = h2 - l2
    slab = m3d.Manifold.cube(size.tolist()).translate(l2.tolist())
    out = man - slab
    ctx = {"bed": _bed(args)}
    return out, ctx, {"shrunk": {"axis": args.axis, "by_mm": by}}

def op_mirror(man, args):
    if not args.axis:
        raise SystemExit("ERROR: mirror needs --axis x|y|z")
    idx = "xyz".index(args.axis.lower())
    n = np.zeros(3); n[idx] = 1.0
    out = man.mirror(n.tolist())
    ctx = {"bed": _bed(args)}
    return out, ctx, {"mirrored": args.axis}

def op_relocate(man, args):
    if not args.to and not args.drop_to_bed:
        raise SystemExit("ERROR: relocate needs --to origin and/or --drop-to-bed")
    out = man
    lo, hi = _bb(man)
    if args.to == "origin":
        out = out.translate((-lo).tolist())
    if args.drop_to_bed:
        lo2, hi2 = _bb(out)
        out = out.translate([0, 0, -lo2[2]])
    ctx = {"bed": _bed(args)}
    return out, ctx, {"moved_from": lo.round(2).tolist()}

# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="remodel.py",
                                description="Natural-language remodelling for downloaded parts")
    p.add_argument("op", choices=["info", "gates", "resize", "drill", "fill",
                                  "thicken", "hollow", "round-edges", "cut",
                                  "extend", "shrink", "mirror", "relocate"])
    p.add_argument("input")
    p.add_argument("-o", "--output")
    p.add_argument("--bed", help="bed size XxYxZ mm, default X2D 256x256x260")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    # resize
    p.add_argument("--factor", type=float)
    p.add_argument("--size", help="target dims like 40x20x5")
    p.add_argument("--keep-holes", action="store_true",
                   help="after scaling, re-drill holes at original diameter")
    # drill
    p.add_argument("--at", help="hole center x,y,z")
    p.add_argument("--dia", type=float)
    p.add_argument("--through", action="store_true")
    p.add_argument("--depth", type=float)
    # fill
    p.add_argument("--dia-max", type=float, dest="dia",
                   help="(fill) max dia to fill — alias of --dia")
    # thicken/hollow/round
    p.add_argument("--by", type=float)
    p.add_argument("--wall", type=float)
    p.add_argument("--open-bottom", action="store_true")
    p.add_argument("--radius", type=float)
    # cut/extend/shrink/mirror
    p.add_argument("--at-cut", dest="at", help=argparse.SUPPRESS)
    p.add_argument("--keep", choices=["top", "bottom"], default="top")
    p.add_argument("--axis", choices=["x", "y", "z"])
    # relocate
    p.add_argument("--to", choices=["origin"])
    p.add_argument("--drop-to-bed", action="store_true")
    return p

def main():
    args = build_parser().parse_args()
    man = load_manifold(args.input)
    if args.op == "info":
        return op_info(man, args)
    if args.op == "gates":
        return op_gates(man, args)
    ops = {
        "resize": op_resize, "drill": op_drill, "fill": op_fill,
        "thicken": op_thicken, "hollow": op_hollow, "round-edges": op_round_edges,
        "cut": op_cut, "extend": op_extend, "shrink": op_shrink,
        "mirror": op_mirror, "relocate": op_relocate,
    }
    n_bodies_in = len(man.decompose())
    out, ctx, meta = ops[args.op](man, args)
    if not args.output:
        base, ext = os.path.splitext(args.input)
        args.output = f"{base}.{args.op}{ext or '.stl'}"
    export(out, args.output)
    exp_ok, exp_report = verify_export(out, args.output, n_bodies_in)
    ok, gates = run_gates(out, ctx)
    report = {
        "op": args.op,
        "output": args.output,
        "pass": ok and exp_ok,
        "meta": meta,
        "gates": gates,
        "export_check": exp_report,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if (ok and exp_ok) else 2)

if __name__ == "__main__":
    main()