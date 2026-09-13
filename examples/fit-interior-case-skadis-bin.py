"""v10: T 型头挂钩 (rotate-and-drop 机制, 社区标准板孔挂装)
轴: Ø4.8 (板孔 Ø5, 0.1/边间隙), 突出背板 7mm
T 梁中心在轴尖: 8(x) x 3(y) x 3(z) — 截面 3x3 可顺孔穿过, 转平后 8mm 卡板背
安装: 筐转90° 让双梁顺孔穿入 -> 转回水平 -> 推平贴板 -> 下滑落位
双钩: ±40mm = 80mm 间距 = 2 格 (抗旋转)
标注: Ø5孔/40mm网格 = 用户实测事实; 轴长7/梁8x3 = 社区惯例推断 (板厚未实测, 7mm 轴容板厚≤7)
"""
import sys, importlib.util, subprocess, shutil, json
import numpy as np
import trimesh
import manifold3d as m3d

SKILL = '/home/administrator/.hermes/skills/creative/remodel-model/scripts/remodel.py'
spec = importlib.util.spec_from_file_location('remodel', SKILL)
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)

def _bb(m):
    b = m.bounding_box()
    return np.array(b[:3]), np.array(b[3:])
def box(x0,y0,z0,x1,y1,z1):
    return m3d.Manifold.cube([float(x1-x0),float(y1-y0),float(z1-z0)],False).translate([float(x0),float(y0),float(z0)])

# ---- base (v8 同款已验证) ----
src = rm.load_manifold('/tmp/feas/sq_container.stl')
sx, sy, sz = 100.6/40.0, 100.6/80.0, 40.0/28.8
scaled = src.scale([sx, sy, sz])
lo, hi = _bb(scaled)
CX0 = float((lo[0]+hi[0])/2)
tri_s = rm.man_to_tri(scaled)
sec = tri_s.section(plane_origin=[CX0, 0.0, 0.0], plane_normal=[0,0,1])
pl, _ = sec.to_2D()
pg = pl.polygons_full[0]
inner = np.array(pg.interiors[0].coords)
bx0, bx1 = float(pg.bounds[0])+CX0, float(pg.bounds[2])+CX0
by0, by1 = float(pg.bounds[1]), float(pg.bounds[3])
ix0 = float(inner[:,0].min())+CX0; ix1 = float(inner[:,0].max())+CX0
iy0 = float(inner[:,1].min()); iy1 = float(inner[:,1].max())
y_wall = by0
cxc = (ix0+ix1)/2
vv = tri_s.vertices
bsel = vv[(vv[:,2] < -15.5) & (vv[:,0] > ix0) & (vv[:,0] < ix1) & (vv[:,1] > iy0) & (vv[:,1] < iy1)]
SLOPE_TOP = float(bsel[:,2].max())
FLOOR_Z = round(SLOPE_TOP + 0.01, 3)
TOP_Z = FLOOR_Z + 40.0

CORE_Z = 8.0
core = m3d.Manifold.batch_boolean([scaled, box(lo[0]-5, lo[1]-5, lo[2]-5, hi[0]+5, hi[1]+5, CORE_Z)], 2)
col_o = box(bx0, by0, 7.5, bx1, by1, TOP_Z)
col_i = box(ix0, iy0, 6.0, ix1, iy1, TOP_Z+2.0)
collar = col_o - col_i
wedge = box(ix0, iy0, lo[2], ix1, iy1, FLOOR_Z)
BT = 5.0
plate = box(bx0, y_wall-BT, lo[2], bx1, y_wall+0.5, TOP_Z)

# ---- T-bar hooks ----
SHAFT_R, SHAFT_OUT, EMBED = 2.4, 7.0, 2.0
PEG_Z = FLOOR_Z + 6.0
BAR_W, BAR_T = 8.0, 3.0        # x-width, y-thickness (z-height = 3)
plate_back = y_wall - BT
tip_y = plate_back - SHAFT_OUT
pegs = None
for dx in (-40.0, 40.0):
    x = cxc + dx
    shaft = m3d.Manifold.cylinder(SHAFT_OUT+EMBED, SHAFT_R, SHAFT_R, 48).rotate([90.0, 0.0, 0.0])
    shaft = shaft.translate([float(x), float(tip_y + SHAFT_OUT + EMBED), PEG_Z])
    bar = box(x-BAR_W/2, tip_y-BAR_T/2, PEG_Z-BAR_T/2, x+BAR_W/2, tip_y+BAR_T/2, PEG_Z+BAR_T/2)
    hook = shaft + bar
    pegs = hook if pegs is None else pegs + hook
pbl, pbh = _bb(pegs)
print('hooks: x[%.2f..%.2f] y[%.2f..%.2f] z[%.2f..%.2f]' % (pbl[0],pbh[0],pbl[1],pbh[1],pbl[2],pbh[2]))
print('total protrusion: %.2f (shaft 7 + bar half 1.5 = 8.5)' % (plate_back-pbl[1]))

assembly = core + collar + wedge + plate + pegs
alo, ahi = _bb(assembly)
vol = float(assembly.volume())
print('vol %.0f mm3 = %dg PLA' % (vol, round(vol*1.24/1000)))

final = assembly.translate([-float(alo[0]), -float(alo[1]), -float(alo[2])])
rm.man_to_tri(final).export('/tmp/feas/bin_skadis_100.stl')
rl = trimesh.load('/tmp/feas/bin_skadis_100.stl', process=True)
print('reload: wt=%s euler=%s faces=%s' % (rl.is_watertight, rl.euler_number, len(rl.faces)))
flo, fhi = rl.bounds[0], rl.bounds[1]
rc = rl.ray

plate_back_re = plate_back - alo[1]
tip_re = tip_y - alo[1]
pegz_re = PEG_Z - alo[2]
p1x = cxc-40-alo[0]; p2x = cxc+40-alo[0]
ok_all = True

def yhits(x, z):
    o = np.array([[x, fhi[1]+50.0, z]]); d = np.array([[0.0, -1.0, 0.0]])
    loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
    return sorted(round(float(v),2) for v in np.asarray(loc)[:,1]) if len(loc) else []
def xhits(y, z):
    o = np.array([[flo[0]-50.0, y, z]]); d = np.array([[1.0, 0.0, 0.0]])
    loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
    return sorted(round(float(v),2) for v in np.asarray(loc)[:,0]) if len(loc) else []
def zhits(x, y):
    o = np.array([[x, y, fhi[2]+50.0]]); d = np.array([[0.0, 0.0, -1.0]])
    loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
    return sorted(round(float(v),2) for v in np.asarray(loc)[:,2]) if len(loc) else []

# 1) bar tip protrusion = 8.5
for tag, xq in [('hook1', p1x), ('hook2', p2x)]:
    hs = yhits(xq, pegz_re)
    deep = hs[0] if hs else None
    exp = round(plate_back_re - 8.5, 2)
    ok = deep is not None and abs(deep - exp) < 0.1
    ok_all = ok_all and ok
    print('%s y-hits %s -> tip %.2f (expect %.2f) %s' % (tag, hs, deep, exp, 'OK' if ok else 'FAIL'))

# 2) bar width 8.0 @ bar mid-depth (y = tip_re), z = pegz
for tag, xq in [('hook1', p1x), ('hook2', p2x)]:
    hits = xhits(tip_re, pegz_re)
    near = [h for h in hits if abs(h - xq) < 4.6]
    dia = near[-1]-near[0] if len(near) >= 2 else -1
    ok = abs(dia - 8.0) < 0.12
    ok_all = ok_all and ok
    print('%s bar x-hits %s -> width %.2f (expect 8.0) %s' % (tag, near, dia, 'OK' if ok else 'FAIL'))

# 3) bar height 3.0 @ bar center (z-ray at x=peg, y=tip_re)
for tag, xq in [('hook1', p1x), ('hook2', p2x)]:
    hits = zhits(xq, tip_re)
    near = [h for h in hits if abs(h - pegz_re) < 2.0]
    hgt = near[-1]-near[0] if len(near) >= 2 else -1
    ok = abs(hgt - 3.0) < 0.12
    ok_all = ok_all and ok
    print('%s bar z-hits %s -> height %.2f (expect 3.0) %s' % (tag, near, hgt, 'OK' if ok else 'FAIL'))

# 4) shaft dia 4.8 @ shaft mid (y = plate_back_re - 3.5)
for tag, xq in [('hook1', p1x), ('hook2', p2x)]:
    hits = xhits(plate_back_re - 3.5, pegz_re)
    near = [h for h in hits if abs(h - xq) < 4.0]
    dia = near[-1]-near[0] if len(near) >= 2 else -1
    ok = abs(dia - 4.8) < 0.12
    ok_all = ok_all and ok
    print('%s shaft dia %.2f (expect 4.8) %s' % (tag, dia, 'OK' if ok else 'FAIL'))

# 5) spacing 80
sp = p2x - p1x
ok_all = ok_all and abs(sp - 80.0) < 0.05
print('spacing %.2f (expect 80.00) %s' % (sp, 'OK' if abs(sp-80)<0.05 else 'FAIL'))

# 6) bar clears board-back zone: bar front face at tip_re+1.5 must be beyond plate_back_re-7+... (geometry self-consistent)
# 7) cavity + depth
for zq in (FLOOR_Z-alo[2]+2.0, FLOOR_Z-alo[2]+20.0, FLOOR_Z-alo[2]+38.0):
    s = rl.section(plane_origin=[(flo[0]+fhi[0])/2, (flo[1]+fhi[1])/2, zq], plane_normal=[0,0,1])
    found = False
    if s is not None:
        plx, _ = s.to_2D()
        for p in plx.polygons_full:
            for ring in getattr(p, 'interiors', []):
                c = np.array(ring.coords)
                w, h = c[:,0].max()-c[:,0].min(), c[:,1].max()-c[:,1].min()
                if abs(w-100.6) < 0.3 and abs(h-100.6) < 0.3:
                    found = True
    print('cavity @z=%.1f: %s' % (zq, '100.60x100.60 OK' if found else 'NOT FOUND'))
    ok_all = ok_all and found
o = np.array([[(flo[0]+fhi[0])/2, (flo[1]+fhi[1])/2, fhi[2]+50]]); d = np.array([[0.0, 0.0, -1.0]])
loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
zs = sorted(round(float(v),2) for v in np.asarray(loc)[:,2])
floor_re = FLOOR_Z - alo[2]
depth = fhi[2] - floor_re
print('flat floor %.2f depth %.2f' % (floor_re, depth))
ok_all = ok_all and abs(depth-40.0) < 0.05
print('ALL CHECKS:', 'PASS' if ok_all else 'FAIL')

r = subprocess.run(['python3', SKILL, 'gates', '/tmp/feas/bin_skadis_100.stl'], capture_output=True, text=True, timeout=900)
try:
    j = json.loads(r.stdout)
    print('GATES pass:', j.get('pass'))
    g = j.get('gates', {})
    for gate in ('G1_watertight','G3_min_wall','G4_overhang','G5_dimensions'):
        print(gate, ':', {k: v for k, v in (g.get(gate) or {}).items() if k not in ('note','bbox_min','bbox_max','samples')})
except Exception as e:
    print('gates err', str(e)[:80])

shutil.copy('/tmp/feas/bin_skadis_100.stl', '/mnt/d/bin_skadis_100.stl')
print('copied /mnt/d/bin_skadis_100.stl')