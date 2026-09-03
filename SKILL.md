---
name: remodel-model
description: "Natural-language remodelling for downloaded 3D-print models (STL/3MF/OBJ): resize with hole-preservation, drill, fill, thicken, hollow, round edges, cut, extend, mirror, relocate. Backed by manifold3d CSG — every write op passes a five-gate validation pipeline (watertight / self-intersection / min-wall / overhang / dimension-chain). Activate when user says: 改模, 改尺寸, 孔做大点, 填孔, 掏空, 倒角, 'make it 5mm longer', 'enlarge the hole to M4', 'the downloaded part doesn't fit', or any edit of an existing mesh."
version: "0.4.0"
license: MIT
keywords:
  - 3d model edit
  - remodel
  - resize keep holes
  - drill
  - fill holes
  - hollow
  - manifold3d
---

# 🔧 动嘴改模 — downloaded-model remodelling

用户一句话 → L1 意图解析 → 单步 CSG 操作 → 五道门校验 → 报告

**核心场景**：下载的挂架差 5mm 卡不进 / 「这个孔做成 M4」/ 「太厚了掏空省料」。
与 makerworld-search 互通：找到模型 → 本 skill 改好 → bambu-studio-ai 打印。

**架构原则（同 makerworld-search）**：manifold3d 是几何后端（布尔永不产生坏网格），
agent 负责意图理解和结果把关。五道门防的是**语义错误**（壁太薄/悬垂/尺寸没对上），
不是几何错误——几何正确性由 CSG 后端构造性保证。

---

## Pipeline（每次改模必走）

```
用户需求（自然语言）
   │
   ▼
[L1 意图解析]（agent 自己做）
   - 操作类型：改尺寸 / 加工孔 / 填孔 / 增厚 / 掏空 / 倒角 / 切割 / 延伸 / 缩短 / 镜像 / 摆位
   - 提取参数：目标尺寸、孔径（M系默认公差）、壁厚、半径、轴向
   - 存疑必问：轴向不明 / 参考面不明 → 先问用户，别猜
   │
   ▼
[L2 执行] python3 scripts/remodel.py <op> <model.stl> [参数] -o out.stl
   - manifold3d CSG 后端，输出必 watertight
   - 自动输出 JSON 报告（op / pass / meta / gates）
   │
   ▼
[L3 把关]（agent 读 JSON 报告）
   - pass=true → 向用户报告：改了什么、尺寸链、哪些门有警告
   - pass=false → 逐门解释：哪道门挂了、数值多少、建议怎么改
   - 反例门（G3/G4）挂了≠不能打印：是「薄壁/悬垂风险提示」，
     报告给用户让用户决策（薄壁件用户可能就是要薄）
```

## 命令速查

| 想做什么 | 命令 |
|---|---|
| 看模型信息+自动检测孔 | `python3 scripts/remodel.py info part.stl` |
| 缩放且**孔径不变** | `python3 scripts/remodel.py resize part.stl --factor 1.2 --keep-holes -o out.stl` |
| 缩放到指定尺寸 | `python3 scripts/remodel.py resize part.stl --size 40x20x5 --keep-holes -o out.stl` |
| 打通孔（M4=4.2） | `python3 scripts/remodel.py drill part.stl --at 30,20,0 --dia 4.2 --through -o out.stl` |
| 打盲孔 | `python3 scripts/remodel.py drill part.stl --at 30,20,4 --dia 8 --depth 2 -o out.stl` |
| 填孔（全部） | `python3 scripts/remodel.py fill part.stl -o out.stl` |
| 填孔（只填 ≤ 某直径） | `python3 scripts/remodel.py fill part.stl --dia 4 -o out.stl` |
| 整体加厚 1mm | `python3 scripts/remodel.py thicken part.stl --by 1 -o out.stl` |
| 掏空（壁厚 2mm） | `python3 scripts/remodel.py hollow part.stl --wall 2 -o out.stl` |
| 掏空+开底（省料） | `python3 scripts/remodel.py hollow part.stl --wall 2 --open-bottom -o out.stl` |
| 倒圆角 1.5（自动保孔） | `python3 scripts/remodel.py round-edges part.stl --radius 1.5 -o out.stl` |
| 切掉一半（留上半） | `python3 scripts/remodel.py cut part.stl --at z=10 --keep top -o out.stl` |
| 加高 8mm | `python3 scripts/remodel.py extend part.stl --axis z --by 8 -o out.stl` |
| 减短 2mm | `python3 scripts/remodel.py shrink part.stl --axis z --by 2 -o out.stl` |
| 镜像（左右手件） | `python3 scripts/remodel.py mirror part.stl --axis x -o out.stl` |
| 摆到原点/落床 | `python3 scripts/remodel.py relocate part.stl --to origin --drop-to-bed -o out.stl` |
| 只跑五道门 | `python3 scripts/remodel.py gates part.stl` |

## L1 意图解析协议（agent 必读）

1. **单位永远是 mm**，M 系螺丝孔径 = 螺纹公称 + 0.2（M3→3.2，M4→4.2，M5→5.2）
2. **「改尺寸」默认问清**：整体缩放还是只改一维？改完的孔要不要保原径？
   —— 默认 `--keep-holes`，因为 99% 的场景是「下载件差一点」，孔是要配螺丝的
3. **「厚一点/薄一点」**：加厚用 thicken（外扩），薄用 shrink（切短）或 hollow（掏空）
4. **「倒角/圆角」**：round-edges 自动保孔（先填→closing→重钻），无需用户提醒
5. **轴向不明必问**：x/y/z 还是「沿孔的方向」？info 先看孔的 axis 字段
6. **改完必报告**：五道门结果 + 最终尺寸链 + 与用户要求的误差（G5 的 error_mm）

## 五道门解读（L3 报告协议）

| 门 | 防什么 | 挂了怎么办 |
|---|---|---|
| G1 watertight | 非流形/漏水网格 | 基本不会挂（CSG 后端保证）；挂了说明输入 STL 本身坏，建议 repair 或换源 |
| G2 self-intersect | 自相交 | 同上，tripwire 性质 |
| G3 min-wall | 壁厚 < 0.8mm（FDM 最小壁） | 真风险：打印会软/断。报告数值，用户坚持就照打（0.4 也能打，就是脆） |
| G4 overhang | >45° 悬垂超 5% 面积 | 提示开支撑或调向；盲孔顶面是常见触发源，属预期内 |
| G5 dimensions | 尺寸链 vs 要求（>0.1mm）或超打印床 | 看 error_mm：超床必失败，其他数值报告给用户 |

**关键语义**：G3/G4 挂 ≠ 拒绝输出——文件照常导出，exit code 2 提示 agent。
薄壁和悬垂是**用户的决策空间**（艺术件薄点没关系），agent 的职责是把数值摆出来。

## 实测战绩（2026-09-03，plate 60×40×4 + 4×M3.2 孔）

- resize 1.2× + keep-holes → 72×48×4.8 精确，孔径 3.209 ≈ 3.2 保住，五门全绿
- round-edges 1.5 → 孔保护机制生效（4 孔全保），五门全绿
- 反例 hollow wall 0.4 → G3 精确拦截（min_wall 0.4 < 0.8）✓ 门是真门
- 16 项回归全过（13 操作 + 3 反例/边界）

## 工程实测笔记（调试图鉴，踩过的坑）

- **manifold3d `bounding_box()` 返回 6 元扁平元组** (xmin,ymin,zmin,xmax,ymax,zmax)，
  不是 [lo, hi] 对——统一走 `_bb()` helper
- **通孔计数用 trimesh `euler_number`**（2-2×genus），**别信 manifold3d 的 `genus()`**
  ——它对钻孔圆柱返回 0，是 CSG 内部 genus 语义，不是拓扑 genus
- **低分段孔壁会击穿 15° 平滑阈值**：parametric 默认分段相邻面偏差恰 30°，
  两档检测（A 档 15° 平滑组 + B 档 45° 环组）才收得全；B 档判环用**法向角谱**
  （面心角谱在低分段下有 >90° 假间隙，法向角谱才对）
- **多边形孔的「真实半径」是顶点圆半径**：拟合给内接圆 r_fit，顶点 r_fit/cos(π/n)。
  重钻用顶点半径，fill 塞子加 1.03 系数，否则留月牙残环
- **孔的轴向范围取顶点集**，不是面心集：低分段孔壁 quad 分成 2 tri，面心 z 坐标
  分两层，面心范围会比真实孔短 1/3——填孔塞子要按 t0..t1（顶点范围）造
- **trimesh `process=True` 会焊坏 minkowski 输出**：merge_vertices 绝对容差焊接
  在致密圆角网格上撕裂流形（11784 面变 non-watertight）。`man_to_tri` 必须
  `process=False`（manifold3d 输出本就是合并过的）
- **thicken/round-edges 会缩小或填死孔**：球和/球差是形态学算子，对孔天然侵蚀。
  thicken 大半径会把薄板上的孔盖死——keep-holes 三步法（填→操作→重钻）是
  round-edges 默认；thicken 需要用户显式 --keep-holes 时同样处理
- **盲孔顶面必触发 G4**（水平朝下面）——属预期，报告时说明是盲孔顶
- **STL 是三角汤**：同一边界边的两个三角形顶点不共享索引。trimesh load 会合并，
  manifold3d Mesh 构造用 float32+uint32 C-order 数组——别传 float64

## 与其他 Skill 的接口

- 上游 **makerworld-search**：搜到模型 → 下载 → 本 skill 改
- 下游 **bambu-studio-ai**：改好的模型 → preview / slice / 打印；AMS 多色 → colorize
- 改不了（自由曲面变形类需求）→ 征询用户走生成兜底（Tripo/Meshy，见 bambu-studio-ai/generate.py）

## 回归场景（任何代码改动后必须重跑）

最小回归集，每条对应一个曾修过的 bug 类：

| 场景 | 命令 | 验证点 |
|---|---|---|
| resize 保孔（核心场景） | `resize plate.stl --factor 1.2 --keep-holes -o t.stl` | 五门全绿；终件 info 检孔=4，dia≈3.2 |
| 低分段孔检测 | `info plate.stl` | holes_detected=4（tier B 路径） |
| 填孔齐平 | `fill plate.stl -o t.stl` 后 `info t.stl` | holes_detected=0，无凸起 |
| 倒角保孔 | `round-edges plate.stl --radius 1.5 -o t.stl` | 孔=4 保留，五门全绿 |
| minkowski 网格完整性 | `thicken plate.stl --by 1 -o t.stl` | G1 watertight=true（process=False 回归） |
| 反例门拦截 | `hollow plate.stl --wall 0.4 -o t.stl` | G3 fail，min_wall≈0.4 |
| 尺寸链 | `extend plate.stl --axis z --by 8 -o t.stl` | G5 z=12 精确 |

测试件生成：`bambu-studio-ai/scripts/parametric.py plate-with-holes --width 60 --depth 40 --thickness 4 --holes 4 --hole-diameter 3.2 --hole-spacing 25 -o plate.stl`