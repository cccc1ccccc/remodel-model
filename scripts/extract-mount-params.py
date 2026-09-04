"""解剖真实 SKÅDIS 配件的挂装接口 — 一手参数提取
证据件(本地):
  SH_LPR_A_001.3mf   — masibu-labs Hooks/Standard_LowProfile (SKÅDIS 板挂式低剖位钩)
  SNS_UHook.3mf      — U 型钩
  bin_115x30x260.stl — Thingiverse 真实 SKÅDIS Bin (挂槽已初测 6.5mm 宽)
输出: 挂装特征实测参数 + 标注渲染图
"""
import sys, importlib.util, zipfile, re, subprocess, base64, os
import numpy as np
import trimesh
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

spec = importlib.util.spec_from_file_location('remodel', '/home/administrator/.hermes/skills/creative/remodel-model/scripts/remodel.py')
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)

def load3mf(path):
    z = zipfile.ZipFile(path)
    xml = z.read('3D/3dmodel.model').decode('utf8', 'ignore')
    verts = re.findall(r'<vertex x="([-\d.eE]+)" y="([-\d.eE]+)" z="([-\d.eE]+)"', xml)
    tris = re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', xml)
    V = np.array([[float(a), float(b), float(c)] for a, b, c in verts])
    T = np.array([[int(a), int(b), int(c)] for a, b, c in tris])
    return trimesh.Trimesh(vertices=V, faces=T, process=True)

def slices_normal(tri, origin, normal, fmt='%.1f'):
    s = tri.section(plane_origin=list(origin), plane_normal=list(normal))
    if s is None:
        return []
    pl, _ = s.to_2D()
    out = []
    for p in pl.polygons_full:
        b = p.bounds
        # to_2D local: add back the two in-plane origin components
        out.append((round(p.area, 1), round(b[0]+origin[0], 2), round(b[1]+origin[1], 2),
                    round(b[2]+origin[0], 2), round(b[3]+origin[1], 2)))
    return out

def prn(tag, rings):
    print(tag + ' :: ' + ' | '.join(f'a={a} [{x0},{y0}..{x1},{y1}]' for a, x0, y0, x1, y1 in rings) if rings else tag + ' :: none')

# ---------- SH_LPR_A_001 ----------
print('====== SH_LPR_A_001 (Standard Low-Profile hook) ======')
hp = load3mf('/tmp/feas/SH_LPR_A_001.3mf')
lo, hi = hp.bounds[0], hp.bounds[1]
print('bbox:', np.round(lo, 2).tolist(), '->', np.round(hi, 2).tolist())
fn = hp.face_normals; fc = hp.triangles_center
for ax, nm in [(1, 'y')]:
    pos = fc[:, ax]
    for sign, sgn in [(1, '+'), (-1, '-')]:
        sel = (fn[:, ax] * sign > 0.9)
        if sel.sum() < 4: continue
        v, c = np.unique(np.round(fc[sel][:, ax], 2), return_counts=True)
        big = [(float(a), int(b)) for a, b in zip(v, c) if b > 10]
        if big:
            print(f'  {nm}{sgn}-facing flats: {big}')
print('--- z-slices (fine, mounting zone) ---')
for z in [-8.6, -8.2, -7.8, -7.2, -6.5, -5.8, -5.2, -4.6, -4.0, -3.4, -2.8, -2.2, -1.6, -1.0, -0.4, 0.2, 0.8]:
    prn(f'z={z:5.1f}', slices_normal(hp, [0, 0, z], [0, 0, 1]))
print('--- y-slices (board-parallel) ---')
for y in [-0.3, -0.8, -1.5, -2.5, -3.5, -4.5, -6.0]:
    prn(f'y={y:5.1f}', slices_normal(hp, [0, y, 0], [0, 1, 0]))
print('--- ray probes along -y (from y=+5) ---')
rc = hp.ray
for (x, z) in [(0.0, -6.0), (0.0, -2.0), (0.0, 0.5), (3.3, 0.5), (-3.3, 0.5), (0.0, 2.0), (2.0, -8.5)]:
    o = np.array([[x, 5.0, z]]); d = np.array([[0.0, -1.0, 0.0]])
    try:
        loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
        hits = sorted(round(float(v), 2) for v in np.asarray(loc)[:, 1]) if len(loc) else []
    except Exception:
        hits = []
    print(f'  ray(x={x:4.1f}, z={z:5.1f}) hits y: {hits}')

# ---------- SNS_UHook ----------
print()
print('====== SNS_UHook ======')
uh = load3mf('/tmp/feas/SNS_UHook.3mf')
lo, hi = uh.bounds[0], uh.bounds[1]
print('bbox:', np.round(lo, 2).tolist(), '->', np.round(hi, 2).tolist())
print('--- z-slices (bottom/mounting zone) ---')
for z in [-8.6, -8.0, -7.0, -6.0, -5.0, -4.2, -3.0, -2.0, -1.0, -0.4, 0.4, 1.5, 3.5]:
    prn(f'z={z:5.1f}', slices_normal(uh, [10, 0, z], [0, 0, 1]))
print('--- y-slices ---')
for y in [-6.7, -6.0, -5.0, -4.0, -3.0, -2.0, -1.0, 0.0, 2.0]:
    prn(f'y={y:5.1f}', slices_normal(uh, [10, y, 0], [0, 1, 0]))
print('--- ray probes along -y ---')
rc = uh.ray
for (x, z) in [(10.1, -8.0), (10.1, -4.5), (10.1, -0.1), (10.1, 3.0), (7.0, -6.0), (13.0, -6.0)]:
    o = np.array([[x, 8.0, z]]); d = np.array([[0.0, -1.0, 0.0]])
    try:
        loc, _, _ = rc.intersects_location(o, d, multiple_hits=True)
        hits = sorted(round(float(v), 2) for v in np.asarray(loc)[:, 1]) if len(loc) else []
    except Exception:
        hits = []
    print(f'  ray(x={x:4.1f}, z={z:5.1f}) hits y: {hits}')

# ---------- bin_115x30x260 slot ends ----------
print()
print('====== bin_115x30x260 slot profile ======')
bn = trimesh.load('/tmp/feas/bin_115x30x260.stl', process=True)
print('--- z-slices near slot bottom end (z=104.5) and top end (z=253) ---')
for z in [102.5, 103.5, 104.2, 105.0, 106.5, 108.5, 251.0, 252.5, 253.3, 254.5, 255.8]:
    prn(f'z={z:6.1f}', slices_normal(bn, [57.5, -9, z], [0, 0, 1]))
print('--- x-slice through slot center x=28.75 ---')
prn('x=28.75', slices_normal(bn, [28.75, -9, 130], [1, 0, 0]))

# ---------- evidence figure ----------
fig = plt.figure(figsize=(17, 10), facecolor='#12121f')
for k, (elev, azim, title) in enumerate([(30, 120, 'hook back/board side'), (25, -60, 'hook front/functional side')]):
    ax = fig.add_subplot(2, 3, k + 1, projection='3d')
    ax.set_facecolor('#12121f')
    ax.plot_trisurf(hp.vertices[:, 0], hp.vertices[:, 1], hp.vertices[:, 2],
                    triangles=hp.faces, cmap='viridis', alpha=0.95, linewidth=0, edgecolor='none')
    ax.view_init(elev=elev, azim=azim)
    ax.set_box_aspect((10, 17.4, 18))
    ax.set_axis_off(); ax.set_title(f'SH_LPR_A_001: {title}', color='w', fontsize=9)
ax = fig.add_subplot(2, 3, 3)
ax.set_facecolor('#12121f')
cols = plt.cm.plasma(np.linspace(0.15, 0.85, 7))
for i, y in enumerate([-0.3, -0.8, -1.5, -2.5, -3.5, -4.5, -6.0]):
    for a, x0, y0, x1, y1 in slices_normal(hp, [0, y, 0], [0, 1, 0]):
        ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], color=cols[i], lw=1.1, label=f'y={y}')
ax.set_title('SH_LPR y-stack (board-parallel cuts)', color='w', fontsize=9)
ax.tick_params(colors='w'); ax.set_aspect('equal'); ax.legend(fontsize=6, facecolor='#12121f', labelcolor='w')
ax = fig.add_subplot(2, 3, 4, projection='3d')
ax.set_facecolor('#12121f')
ax.plot_trisurf(uh.vertices[:, 0], uh.vertices[:, 1], uh.vertices[:, 2],
                triangles=uh.faces, cmap='viridis', alpha=0.95, linewidth=0, edgecolor='none')
ax.view_init(elev=25, azim=-60)
ax.set_box_aspect((19.4, 14, 25.8))
ax.set_axis_off(); ax.set_title('SNS_UHook', color='w', fontsize=9)
ax = fig.add_subplot(2, 3, 5)
ax.set_facecolor('#12121f')
for i, z in enumerate([-8.6, -7.0, -5.0, -3.0, -1.0, -0.4, 0.4, 1.5]):
    for a, x0, y0, x1, y1 in slices_normal(uh, [10, 0, z], [0, 0, 1]):
        ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], color=cols[min(i, 6)], lw=1.1, label=f'z={z}')
ax.set_title('UHook z-stack (mounting zone)', color='w', fontsize=9)
ax.tick_params(colors='w'); ax.set_aspect('equal'); ax.legend(fontsize=6, facecolor='#12121f', labelcolor='w')
ax = fig.add_subplot(2, 3, 6)
ax.set_facecolor('#12121f')
for i, z in enumerate([104.2, 105.0, 106.5, 108.5, 251.0, 253.3]):
    for a, x0, y0, x1, y1 in slices_normal(bn, [57.5, -9, z], [0, 0, 1]):
        ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], color=cols[min(i, 6)], lw=1.1, label=f'z={z}')
ax.set_title('bin slot cross-sections (entry/capture zone)', color='w', fontsize=9)
ax.tick_params(colors='w'); ax.set_aspect('equal'); ax.legend(fontsize=6, facecolor='#12121f', labelcolor='w')
plt.tight_layout()
plt.savefig('/tmp/feas/skadis_interface_evidence.png', dpi=105, facecolor='#12121f')
import shutil
shutil.copy('/tmp/feas/skadis_interface_evidence.png', '/mnt/d/skadis_interface_evidence.png')
print('\nfigure -> /mnt/d/skadis_interface_evidence.png')