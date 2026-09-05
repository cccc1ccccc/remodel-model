---
name: remodel-model
description: "Natural-language remodelling for downloaded 3D-print models (STL/3MF/OBJ): resize with hole-preservation, drill, fill, thicken, hollow, round edges, cut, extend, mirror, relocate. Backed by manifold3d CSG — every write op passes a five-gate validation pipeline (watertight / self-intersection / min-wall / overhang / dimension-chain). Activate when user says: 改模, 改尺寸, 孔做大点, 填孔, 掏空, 倒角, 'make it 5mm longer', 'enlarge the hole to M4', 'the downloaded part doesn't fit', or any edit of an existing mesh."
version: "0.6.0"
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

0. **先锁口径再动手（2026-09-04 用户翻车修正）**：fit/改模需求开工前，必向用户
   复述并确认四件事——①对象真实尺寸（能实测就实测，别用名义值）；②「放下」的
   语义（坐进内腔底面 / 全包围 / 靠背托底——语义不同则件型完全不同，做错即
   「完全不可用」）；③余量策略（FDM「刚好」= 每边 +0.3mm 插入余量，100×100
   方物 → 内腔 100.6×100.6，精确 100.0 是放不进去的）；④硬约束清单（如 SKÅDIS
   挂装接口 40mm 网格必须保持）。用户说「重新描述需求」= 旧交付物作废、新口径
   全权，别为旧方案辩护。

**改模铁律（2026-09-05 用户定版，两条都踩过坑）**：

① **改模 ≠ 建模**。「改模承诺 = 在真实下载件上做修改」。从零参数化重建只是
   兑底中的兑底——重建件的结构语言（挂钩形态/镂空位置/公差风格）不等于原作，
   用户一眼识破（「这不是在那个模型基础上改的」）且大概率不可用。

② **下载不到原件 → 直接向用户要文件，并且一开始就说清楚**。下载路径全部
   试尽（MW 登录墙 / CDN 401 / CF 挑战 / GitHub 镜像）仍拿不到时，**立刻
   明说「我拿不到原件，需要你下载后发我」，同时停下等待**——不要转入
   从零重建然后装作完成了需求。用户原话：「如果你做不到我的需求，你可以直接
   告诉我，而不是白白做无用的尝试浪费 token」。半途告知也比沉默重建强：
   分析原作设计语言期间就应说「无法下载原件，方案 A 等你给文件 / 方案 B
   按图片分析重建（有偏差风险）」让用户选。

③ **拿到原件后：先解剖再动刀**。切片剖面族（ASCII 可视化）+ contains 射线
   实测内腔/壁位/挂槽坐标，画出结构图后再定修改方案；动刀优先 boolean 手术
   （劈半平移/挖腔/填补）而非重造。每个手术步骤后跑一扇验证门（位置/尺寸/
   水密/单件），全绿才交付。

1. **单位永远是 mm**，M 系螺丝孔径 = 螺纹公称 + 0.2（M3→3.2，M4→4.2，M5→5.2）
2. **「改尺寸」默认问清**：整体缩放还是只改一维？改完的孔要不要保原径？
   —— 默认 `--keep-holes`，因为 99% 的场景是「下载件差一点」，孔是要配螺丝的
3. **「厚一点/薄一点」**：加厚用 thicken（外扩），薄用 shrink（切短）或 hollow（掏空）
4. **「倒角/圆角」**：round-edges 自动保孔（先填→closing→重钻），无需用户提醒
5. **轴向不明必问**：x/y/z 还是「沿孔的方向」？info 先看孔的 axis 字段
6. **改完必报告**：五道门结果 + 最终尺寸链 + 与用户要求的误差（G5 的 error_mm）
7. **「放得下 X」= 内腔需求，不是外廓**：resize --size 是外廓尺寸。换算 = 内 + 2×壁厚 + 1-2mm 活动量
   （FDM 单边活动量 0.3mm 起步）。封闭容纳超床时（外廓 > 床容量）**主动给出开放端摇篮方案**
   （见 references/long-object-design.md），别硬缩破坏用户需求。
   **fit-interior 四步协议（2026-09-04 真实件全链验证）**：
   ① 开放腔实测 = 切片内环 + 射线序列（decompose 假分量陷阱见工程笔记），斜底件另扫底面 z 分布
   ② 逐轴因子 = 目标内腔 / 实测内腔（非均匀缩放保外形语义，壁厚随之缩放要单独报告）
   ③ 壁厚>2mm 需求或缩放后壁 <0.8mm → 改壳重建路径（缩放掏壳法 hollow 只对实心块语义正确）
   ④ 底面坡度 → 填平楔 + 净深补偿；挂装接口（孔/销/槽）用真实社区件实测参数复刻，别凭印象
   实测样本：SNS 筐 40×80×28.8 内腔 → 100.6×100.6×40，因子 2.515/1.2575/1.389，
   壁 0.8→2.01/1.01，**SKÅDIS 板孔直挂 = T 型头挂钩**（rotate-and-drop：轴 Ø4.8 穿 Ø5 孔 +
   末端 8×3×3 横梁，安装 = 转 90° 穿入 → 转平 → 下滑落位；梁 8>5 拉不出，双钩 80mm=2 格转不动）。
   **「突出销≠挂钩」**（2026-09-04 用户纠正）：光杆销在 Ø5 孔里纯摩擦，功能上是废的；
   任何「挂上」需求必须给特征一个**防脱机制**（横梁/蘑菇头/钩唇），并先做力学自检：
   蘑菇头 Ø6.3 挤 Ø5 孔需单边 0.65mm 弹性压缩——PLA 销+纤维板孔都没这个弹性，会被否；
   无应力可逆机制（T 梁转 90° 过孔）才是硬质材料正解。
   **真实社区件解剖数据（别凭印象编挂装参数）**：masibu Skadis_Storage 全套（SH_LPR 钩/UHook/
   SquarensertMount）实测是**轨道+穿板 toggle 螺母体系**（双弹簧指 2.5mm 间距卡 SNS 鳍、
   Teardrop 鳍 4mm、钥匙孔 4.4×11@13.8），Thingiverse 筐是 57.5mm 长槽（非 40 网格）——
   都不是板孔直挂，从它们身上提不出板孔挂装参数；Ø5/40mm 网格才是宜家原生接口（用户提供事实）
8. **「刚好放下 X」= fit-interior 语义**（尚无现成 op，协议见 references/fit-interior-case.md）：①切片环+射线实测真实内腔（**禁信布尔差分量——开放腔会出幽灵假数据**）→ ②逐轴缩放因子 = (目标内腔+2×clearance)/当前内腔 → ③非均匀 scale → ④切片实测复核（误差>0.05 报告）→ ⑤**必报壁厚后果**（壁被同比缩放，<0.8 触 G3，0.8-1.5 给警告）→ ⑥圆角 vs 方形物体角部验算
9. **口径先锁再动手**（2026-09-04 返工实录）：前一轮「放得下 26×10」被做成靠背摇篮，用户判「完全不可用」——件几何五门全绿但答非所问。执行前必须复述口径三要素：内腔还是外廓、深度、**挂装体系**（SKÅDIS 原生 5mm 孔/40 网格直挂 vs SNS 法兰+挂座等第三方体系——文件名带 SKÅDIS ≠ 原生直挂，切接口特征判别）。问询超时无回复 → 按用户原话字面义选默认并**显式告知决策**，继续执行

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

## 实测战绩（2026-09-03，双层验证）

**合成件回归（plate 60×40×4 + 4×M3.2 孔）**：
- resize 1.2× + keep-holes → 72×48×4.8 精确，孔径 3.209 ≈ 3.2 保住，五门全绿
- round-edges 1.5 → 孔保护机制生效（4 孔全保），五门全绿
- 反例 hollow wall 0.4 → G3 精确拦截（min_wall 0.4 < 0.8）✓ 门是真门
- 16 项回归全过（13 操作 + 3 反例/边界）

**真实件端到端（2026-09-03 可行性验证，GitHub 下载 SKÅDIS Bin 80×50×80）**：
- 下载→info→resize 全链跑通，G5 两次精确拦截超床件（270 外廓 fits_bed=false）
- 45° 斜放数学推演推翻自己最初的方案（旋转包络 272×272 仍超床）
- 最终交付开放端摇篮 250×15×120（五门全绿，166g PLA）——床容量推演方法论
  沉淀在 `references/long-object-design.md`

## 工程实测笔记（调试图鉴，踩过的坑）

> 12 条完整坑位表（含 trimesh process 撕裂流形、镜像过原点、共面布尔无 seam、Mesh ctor dtype 等）沉淀在 **bambu-studio-ai/references/manifold-examples.md §6**——manifold3d 通用知识在那边，本节保留与本 skill 工作流直接相关的条目。

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
- **STL 导出重载后 trimesh 报 non-watertight ≠ 真开**（2026-09-03 真实件实测）：
  remodel 导出的 STL 用 `trimesh.load` 直查可能 watertight=False——这是三角汤重载的
  顶点合并问题。**判读用 remodel 自己的 `load_manifold → man_to_tri` 管线**
  （manifold3d 构造性合并），实测同文件走该管线 watertight=True
- **trimesh `ray.intersects_id` 返回值随参数变**（实测 4.12）：`multiple_hits=False` +
  `return_locations=True` 返回 **3 元组** (face_ids, ray_ids, locations)——不是直觉的
  2 元组；写解包前先跑一次 1 条射线探形，别按记忆写
- **内腔测量别用顶打射线**：开放容器（开口朝前/朝上）从顶部打网格射线只能打到
  封闭面，interior depth 会读出 1mm 级假值。**正确方法 = 布尔差法**：外包围盒 − 部件
  → `decompose()` 逐分量判「bbox 完全嵌在部件 bbox 内」→ 即内腔。注意 decompose 返回
  的分量带符号（负体积分量 = 原部件本体），只取正体积且内嵌的
- **多体/开放腔的 decompose 陷阱**：前面+顶面都开放的托盘，其空腔与外界连通——
  布尔差分解不出独立内腔分量（属设计正确，不是 bug）。这种件直接用结构尺寸推演
- **decompose 假分量陷阱（2026-09-04 实测推翻自家方法）**：布尔差法测内腔对**开放腔件**
  不可靠到会反噬——SNS 敞口筐（真实内腔 40×80×28.8）被 decompose 报出
  「封闭腔 20×40×13.8 @ y<0 半边」的假分量，vol 与假腔精确吻合，极具欺骗性。
  开放腔的正测法 = **切片内环 + 三向射线交点序列**（环宽即内腔，射线序列即实/空分层）。
  布尔差法只对封闭腔可信；两法结果矛盾时以射线法为准
- **manifold3d `rotate()` 是角度制**（2.x py 绑定实测）：`rotate([1,0,0], π/2)` 签名不存在，
  `rotate([π/2,0,0])` 是 1.57° 微转 ——2026-09-03 摇篮「孔只啃月牙坑」的根因就是它。
  转 90° 写 `rotate([90.0, 0.0, 0.0])`。同理 `cylinder(height, rLow, rHigh, segments)` 四参
  顺序——v3 曾把 segments 位传成 rHigh 生成了 r=48 怪物。交集无 `&`/`intersect()`，
  用 `Manifold.batch_boolean([a, b], 2)`（0=add?1=sub,2=intersection, 实测）
- **trimesh `section().to_2D()` 返回局部坐标系**（以切面原点为中心），不是世界坐标——
  两个轴都要加回切面原点才是世界值。v5 背板/销钉因把局部当世界，整体错位 64mm
  （bbox 171mm 的来源），特征校验全绿但件是错的。截面轮廓用于构造件时必先 + 原点
- **斜壁件接直壁会产生楔形薄缝**：筐壁带脱模斜度时，直板嵌壁 0.5mm 在斜壁外扩侧
  （z=10 处外扩 0.38）只剩 0.12mm 实接 → CSG 残留 0.39mm 楔形薄壳，G3 抓到才暴露。
  修法：直壁结构只在斜壁区以下搭接（core 切到斜壁起点 z=8，collar 从 7.5 起）
- **底面坡度必须实测**：「放平 X」类需求先扫腔底顶点 z 分布——SNS 筐底是斜的
  （后高前低差 2.8mm，挂座配合设计），标题/外形看不出来。放平 = 填平楔到斜底最高点，
  再把净深补偿到需求值（顶加高 floor_z+40）
- **euler 负值≠缺陷**：原筐碟形底拓扑会让终件 euler=-6（4 "tunnels"），但 watertight ✓
  + winding consistent ✓ + 全切片/射线校验过 = 原件固有拓扑，照打
- **特征存在性 ≠ 五道门职责**（2026-09-03 摇篮翻车实录）：parametric 构建时肋板
  cube 放进了唇沿体积内部（并集吞掉、零效果），孔圆柱轴没旋转（沿板面方向只啃
  0.5mm 月牙坑）——**五道门全绿但件是光板**。G1/G2 验网格质量，G3/G4/G5 验物理
  参数，没有任何门验「特征真的在件上」。**特征构建后必补存在性实测**：
  ① 通孔数 = (2−euler_number)/2；② 特征所在平面切片数环数（外轮廓+孔数）；
  ③ 特征方向的扫掠切片 bbox。manifold3d cylinder 沿 +Z 从 0 到 height **不居中**，
  旋转后必须按 bounding_box() 实测中心对位，别假设
- **decompose 会编造幽灵腔**（2026-09-04 实测）：开放腔薄壁筐做布尔差（外盒−件）
  → decompose 分出「封闭内腔 20×40×13.8，vol=10,966」的假分量，尺寸体积自洽极具
  欺骗性——射线+切片证明真实内腔是 40×80×28.8 敞口大腔。比已记录的「开放腔分解
  不出分量」更阴险：**它会无中生有**。开放件量内腔只信三信号：①逐层切片环 bbox
  （壁厚=(外−内)/2）②竖直射线命中对面数（敞口腔中柱只中 2 面）③体积交叉验算
  （底+壁+法兰理论值 vs 实测）。协议全案见 references/fit-interior-case.md
- **hollow 只对实心块有意义**（2026-09-04）：hollow = minkowski 球侵蚀，对已有内腔
  的件 eroded 核跟随外形而非目标腔，产出不可预期的壳。开口筐先实心化（腔体矩形块
  并集填死，注意下条 center 语义）再 hollow
- **Manifold.cube 的 center 是原点语义陷阱**（2026-09-04）：cube([...], True) 中心
  在原点、translate 后**中心**落在目标；cube([...], False) 从原点角拉伸、translate
  后**角**落在目标。填腔塞子/背板定位用错语义，块整体错位（bbox 膨胀 10mm 级）
  且**静默**——不报错只出坏件
- **rotate() 签名是单向量**（2026-09-04）：Manifold.rotate(v: Doublex3) 只收一个
  旋转向量（绕 x 转 90° = rotate([np.pi/2, 0, 0])），不收轴+角度两参数（TypeError）
- **3MF 解析要点**（2026-09-04）：顶点/三角直接正则提取 `<vertex x=...>` /
  `<triangle v1=...>` 即可，无需完整 XML 解析；`<item>` 可能带 transform（12 数
  4×3 矩阵），无 transform 时 raw 坐标即世界坐标——bbox 与模型名对不上先查 transform
- **挂件背挂结构必须逐点复刻原版，禁止自创连接（2026-09-05 用户两次抓出）**：
  SKÅDIS 挂接 = 板销在挂件下滑时被**钩块底边**托住 → ①销的全高通道（钩块下方、
  底托背面）必须无任何横向阻挡：底托只做到内层板背面（y=内层厚），不得延伸到
  外板平面；②钩块下方禁止加连接桥，块与内层的连接走**顶部实心段**（缝开口在
  下 ~7mm + 实心封顶在上 ~6mm，从原版射线剖面逐层复刻）。
  vision 检查要问具体缺陷（「块下方有无多余突出」「底部有无向背突出」），
  宽泛问题（「结构对吗」）会漏检。
  **交付门 = 销通道 contains 扫描**：沿销深度（y=板销中面）逐 0.5mm 扫 z，
  实体段只允许出现在钩块本体区间——vision 看图会漏，射线扫描不会。
  双层背板参数表（十号充电宝挂件射线实测）：内层 2.4 / 缝 5.15 / 外板 5.25 /
  **块宽 4.9**（2026-09-06 用户打印打脸 5.4：钩块要插进 Ø5 孔，宽必须 <5，
  原版截面法实测 y=24 层恒宽 4.90、中心 ±20；v5 曾误写 5.4@±20.5 导致
  插不进）×高 13 / 上下排距 40 / 底托背=内层背面。
  **钩块宽度是插孔尺寸不是外观尺寸**：量原版必须扫「插入段」的 x 宽度，
  且打印件公差吃掉 0.1mm 后还能进 → 4.9 是验证值，别自作聪明放大。
  **SKÅDIS 竖向网格 = 20mm**（2026-09-05 圆物件复算确认）：原版中央块位于
  上下排正中（各自距离 ≈20）——即中央块也是真实销位，不是装饰；"减半挂钩"
  = 5 孔位 → 3 孔位（下排 2 + 中央 1，竖向占 2 格）。改腔高时背板必须
  仍覆盖全部钩块（背板顶 = 最高钩块顶 + 2），否则高处钩块悬空离群
- **相邻 box 纯共面贴合不保证焊接（2026-09-05 v3 教训）**：batch_boolean Add 后
  两个仅共面接触的 box 仍是独立体（decompose 报多件）。组合构件一律让相邻
  box **体积重叠嵌入 0.5~1mm**（如连接桥 y 从 0.6 起而非 2.4）；每次布尔后
  `len(M.decompose())==1` 过门再谈别的
- **重建挂接件先钉坐标系再布特征（2026-09-05 v3 教训）**：先画背挂坐标系
  （板面 y=外板背 / 内层 0..2.4 / 缝 2.4..7.55 / 外板 7.55..12.8 / 基座顶 z=0），
  挂接排布只能落在**基座顶以上的背板有效区**——v3 把下排钩块中心放在基座
  之下（z=-19.25 vs 基座 -6..0）导致钩块悬空离群、decompose 报多件
- **「改 vs 重建」量级判据**：内腔单维变化 >~1.3× 时劈半/缩放手术会连带扭曲
  挂接几何 → 转为「同设计语言重建」：逐点射线解剖原版挂接机构（销托点/
  通道/封顶位置），腔体全新参数化，挂接 1:1 复刻，路径切换必须向用户声明
- **导出后必须回读验证（2026-09-05 用户报「组件满天飞」教训）**：STL/3MF 写盘后
  重新 load 并检查 `len(mesh.split(only_watertight=False))==1` —— kernel 内变量
  正确 ≠ 磁盘文件正确（中间重跑/旧文件覆盖都会导致交付旧版多壳件，BS 打开
  就是满盘飞组件）。交付门：单 body + watertight + 体积对账，缺一不交付
- **trimesh 3MF 导出缺 build item**：导出的 3dmodel.model 没有
  `<build><item objectid="1"/></build>`，BS 打开不显示；解包手补 XML 再打包，
  顺便把 object name 里的 .stl 后缀改掉
- **manifold3d v2 `cube()` 非居中（2026-09-05 实测）**：`m3d.Manifold.cube([sx,sy,sz])`
  生成 `[0..size]` 而非居中在原点！平移时传角点不传中心，否则全部几何整体偏移一半
  （batch_boolean 能跑通但结果全错）。自测法：cube 后查 bbox 是否 `[0..s]`
- **batch_boolean 顺序敏感（2026-09-05 实测，v2.x）**：`batch_boolean([大盒, M], Intersect)`
  在大盒远超 M bbox 时可能返回荒唐小值（2.2 vs 正确 18.0），交换参数顺序或缩小
  盒到实际邻域后恢复。用 `m3d.OpType` 枚举（Add/Intersect/Subtract），别传裸数字
  （v2.x 裸 int 会 TypeError）；Manifold 构造：`m3d.Mesh(vert_properties=..., tri_verts=...)`
  后 `m3d.Manifold(vm)`，直接传 trimesh 对象会 TypeError
- **ASCII 剖面族是解剖下载件的利器**（2026-09-05 充电宝挂件全链验证）：对陌生 3MF
  逐层 `mesh.contains` 网格扫描打印字符图，内腔/壁厚/挂槽位置一目了然，比渲染猜
  可靠——渲染会被深度排序伪影骗（大三角形穿模出假碎片），ASCII 剖面不会
- **渲染伪影 ≠ 几何缺陷**（2026-09-05）：matplotlib Poly3DCollection 深度排序对
  大三角形会画出错位碎片/穿模假象，vision 复检会误报「碎面/悬空」。客观判据：
  ①腔体空区三角计数 = 0；②体积对账（分件体积和 vs 总体积，误差<0.1%）；
  ③watertight + 单连通。三者全绿就是渲染锅，细分三角形（subdivide）重渲染即可
- **vision_analyze 超时应急预案**：连续 2 次超时就放弃图像路线，切 ASCII 剖面 +
  顶点统计的纯几何验证（本次充电宝挂件最终就是靠这个交付的）
- **底模资格门——下载件名字会骗人，改造前先解剖（2026-09-04 实测）**：本地旧件
  `bin_115x30x260.stl` 名字带 bin，实测却是 466mm² 恒截面薄壁竖板（无内腔可改）；
  面法向提取挂槽壁（|nx|>0.85）实测槽宽 6.5mm ✓ 但槽心间距 57.5mm ✗——不是
  SKÅDIS 40mm 网格的倍数，与标准板挂装不匹配。对不合格底模做任何 fit 操作都是
  徒劳。**资格三查**：① z 向切片扫掠——真容器跨腔体时截面积应「大→小→大」，
  恒定小截面 = 实心板；② 挂装接口实测——面法向提取槽/孔壁坐标，间距对 40mm
  网格（槽宽 6mm+ 是挂件常见钥匙孔接口，与 5mm 圆孔同属标准接口，保孔规则同）；
  ③ 内腔投影 ≥ 目标件 + 余量——不到就是选错底模，换件别硬改
- **底模下载源现实矩阵（2026-09-04 全通道实测，2026-09-05 补充 MW 3MF 通道）**：
  MakerWorld 文件下载要登录（design-service API 只给元数据，选件比尺寸不用登录）；
  3MF CDN 直链 401（`/model/{hash}/{profileId}/...` 无 token 全 401，别浪费调用）；
  design-service `/instances` 能拿到 instanceId 和封面，但文件端点全 404；
  无头浏览器过不了 CF checkbox 挑战（「Just a moment」卡死）；
  **最快路径 = 直接请用户下载后发文件**（一次澄清，十分钟内解决）。
  Thingiverse CF 是**按天概率**——09-03 全通、09-04 全浏览器头×3 / API / CDN 子域全 403，
  无头浏览器过不了 checkbox 挑战（iframe 不渲染），隔天重试是正经策略；
  **GitHub 镜像仓库是最稳机器下载源**：`gh api "search/repositories?q=skadis"` 找镜像
  → Contents API base64 取件（raw 直连超时时验证过的绕行，见 github skill api-push.md §4c）。
  已知可用：masibu-labs/Skadis_Storage（GPL-3.0，Square/Round 容器 3MF + Hooks
  + ToolHolders）。详见 references/base-model-download-sources.md

## References

- `references/long-object-design.md` — 长物收纳的床容量推演链（封闭方案全灭的数学）+ 开放端摇篮已验证设计（260×100 案例）+ 下载件结构判别法
- `references/fit-interior-case.md` — 「刚好放下 X」全链案例（2026-09-04）：SNS 敞口筐改 SKÅDIS 原生直挂 100×100 方物收纳。含口径锁定协议、下载通道实测（CF 封锁时 gh api Contents API base64 兜底）、开放腔三信号解剖协议、逐轴缩放链+壁厚后果、SNS vs SKÅDIS 挂装体系判别、fit-interior op 设计草案（未实现，晋升需跑回归）
- `scripts/render_stl.py` — STL 双视角 PNG 渲染（matplotlib Lambert 光照，无需 Blender/vision；中文需挂 Windows 字体，坑位见脚本头注释）——「改好发用户看看」的固定出口
- `references/base-model-download-sources.md` — 底模下载源矩阵与绕行实测（MW 登录墙 / TV CF 按天概率与隔天重试 / GitHub 镜像 gh api 路线 / 已知可用 SKÅDIS 仓库清单）

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

**fit-interior 相关回归（草案期只做协议级验证，op 落地后升级为命令回归）**：
- 开放腔解剖：三信号（切片环/射线/体积验算）互证，布尔差分量仅作参考必弃核
- 口径锁定：内腔/外廓/深度/挂装体系四要素缺一先问，超时默认+显式告知

测试件生成：`bambu-studio-ai/scripts/parametric.py plate-with-holes --width 60 --depth 40 --thickness 4 --holes 4 --hole-diameter 3.2 --hole-spacing 25 -o plate.stl`