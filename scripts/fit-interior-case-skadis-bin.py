"""底面不是碟形! 顶点 z 从 0 到 4.44 连续分布 — 底是**斜坡**!
最高点 z=4.44 在 y[13.0..16.5] (腔的背部窄条), 最低 z=0 在前部?
原筐底 1.2mm 平底 → 缩放后 1.66 平底… 但 z 分布 0..4.44!
→ 原筐底部有**背部增高设计** (靠背侧底厚, 前侧底薄 — SNS 筐配合挂座的斜底!)
斜底对"放 100x100 物体"影响: 物体会斜着放 (前低后高 4.44-1.66 ≈ 2.8mm 斜差)
或放不平 (只接触后缘)。"刚好放下"语义 → 物体必须平放!
→ 必须垫平底: 加一个填充楔 (把腔底斜坡填平到 z=4.44? 不 — 物体放底上, 底要平:
  填平到斜底最高点 → 有效深度 = 41.67-4.44-0(顶) = 37.2 < 40 需求!
  40 深 + 平底 4.44 = 顶到 45 → 超出原筐顶 41.67 → 需要加高筐体 3.3mm!
  或者: 切掉斜底换平底 — 原筐底是斜的, 切掉后壁变短。
  最干净: collar 加高 + 腔底填平楔。
重新推尺寸链:
  平底顶面 z = 4.44 (填平楔)
  需求腔深 40 → 筐顶开口 z = 44.44
  collar 现到 41.67 → 加高 2.77 到 44.44
  背板同步加高到 44.44
  销 z 移到平底上方 6 → z=10.44 (避开填平楔, 楔在 y 背侧最高)
最终: 内腔净深 40 (从平底 4.44 到口 44.44), 内腔 100.6x100.6 ✓ 物体平放 ✓
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

# 斜底实测 (世界系): 底最高点 z + 位置
vv = tri_s.vertices
bsel = vv[(vv[:,2] < -15.5) & (vv[:,0] > ix0) & (vv[:,0] < ix1) & (vv[:,1] > iy0) & (vv[:,1] < iy1)]
SLOPE_TOP = float(bsel[:,2].max()) if len(bsel) else -13.8*sz
print('slope top z=%.3f (world)' % SLOPE_TOP)
FLOOR_Z = round(SLOPE_TOP + 0.01, 3)          # 平底面
TOP_Z = FLOOR_Z + 40.0                         # 开口顶
print('flat floor z=%.2f, top z=%.2f (need collar above core)' % (FLOOR_Z, TOP_Z))

# v8: core 切到 z=8 (直壁区以下), collar 7.5..TOP_Z, 填平楔 (腔底到 FLOOR_Z)
CORE_Z = 8.0
core = m3d.Manifold.batch_boolean([scaled, box(lo[0]-5, lo[1]-5, lo[2]-5, hi[0]+5, hi[1]+5, CORE_Z)], 2)
col_o = box(bx0, by0, 7.5, bx1, by1, TOP_Z)
col_i = box(ix0, iy0, 6.0, ix1, iy1, TOP_Z+2.0)
collar = col_o - col_i
# 填平楔: 腔内 z 底..FLOOR_Z (斜底上方补平)
wedge = box(ix0, iy0, lo[2], ix1, iy1, FLOOR_Z)
BT = 5.0
plate = box(bx0, y_wall-BT, lo[2], bx1, y_wall+0.5, TOP_Z)
PEG_R, PEG_OUT, PEG_EMBED = 2.4, 7.0, 2.0
PEG_TOT = PEG_OUT + PEG_EMBED
PEG_Z = FLOOR_Z + 6.0                        # 平底上方 6mm
pegs = None
for dx in (-40.0, 40.0):
    cyl = m3d.Manifold.cylinder(PEG_TOT, PEG_R, PEG_R, 48).rotate([90.0, 0.0, 0.0])
    tip_y = (y_wall-BT) - PEG_OUT
    cyl = cyl.translate([float(cxc+dx), float(tip_y+PEG_TOT), PEG_Z])
    pegs = cyl if pegs is None else pegs + cyl

assembly = core + collar + wedge + plate + pegs
alo, ahi = _bb(assembly)
vol = float(assembly.volume())
print('assembly: %s -> %s vol=%.0f (%dg)' % (np.round(alo,1).tolist(), np.round(ahi,1).tolist(), vol, round(vol*1.24/1000)))

final = assembly.translate([-float(alo[0]), -float(alo[1]), -float(alo[2])])
rm.man_to_tri(final).export('/tmp/feas/bin_skadis_100.stl')
rl = trimesh.load('/tmp/feas/bin_skadis_100.stl', process=True)
print('reload: wt=%s euler=%s' % (rl.is_watertight, rl.euler_number))

flo, fhi = rl.bounds[0], rl.bounds[1]
rc = rl.ray
def yhits(x, z):
    o = np.array([[x, fhi[1]+50.0, z]]); d = np.array([[0.0, -1.0, 0.0]])
    loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
    return sorted(round(float(v),2) for v in np.asarray(loc)[:,1]) if len(loc) else []

plate_back = (y_wall-BT) - alo[1]
tip_expect = plate_back - PEG_OUT
ok_all = True
for tag, xw, want in [('peg1', cxc-40-alo[0], tip_expect), ('peg1off', cxc-40+2.6-alo[0], plate_back),
                      ('mid', cxc-alo[0], plate_back), ('peg2', cxc+40-alo[0], tip_expect)]:
    hs = yhits(xw, PEG_Z-alo[2])
    deep = hs[0] if hs else None
    ok = deep is not None and abs(deep - want) < 0.1
    ok_all = ok_all and ok
    print('%s: %s -> %.2f %s' % (tag, hs, deep, 'OK' if ok else 'FAIL'))

# 平底+腔: 射线从顶中心打: 平底面 z_re = FLOOR_Z-alo[2]
floor_re = FLOOR_Z - alo[2]
top_re = ahi[2] - alo[2]
o = np.array([[(flo[0]+fhi[0])/2, (flo[1]+fhi[1])/2, fhi[2]+50]]); d = np.array([[0.0, 0.0, -1.0]])
loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
zs = sorted(round(float(v),2) for v in np.asarray(loc)[:,2])
print('center ray: %s | flat floor z=%.2f depth=%.2f' % (zs, floor_re, zs[-1]-floor_re))
ok_all = ok_all and abs(zs[-1]-floor_re) < 0.05 and abs((fhi[2]-floor_re)-40.0) < 0.05

for zq in (floor_re+2.0, floor_re+20.0, floor_re+38.0):
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

print('ALL CHECKS:', 'PASS ✓' if ok_all else 'FAIL ✗')

r = subprocess.run(['python3', SKILL, 'gates', '/tmp/feas/bin_skadis_100.stl'], capture_output=True, text=True, timeout=900)
try:
    j = json.loads(r.stdout)
    print('GATES pass:', j.get('pass'))
    g = j.get('gates', {})
    for gate in ('G1_watertight','G3_min_wall','G4_overhang','G5_dimensions'):
        print(gate, ':', {k: v for k, v in (g.get(gate) or {}).items() if k not in ('note','bbox_min','bbox_max','samples')})
except Exception as e:
    print('gates err', str(e)[:80])