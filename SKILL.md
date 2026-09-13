---
name: remodel-model
description: "Natural-language remodelling for downloaded 3D-print models (STL/3MF/OBJ): resize with hole-preservation, drill, fill, thicken, hollow, round edges, cut, extend, mirror, relocate. Backed by manifold3d CSG — every write op passes a five-gate validation pipeline (watertight / self-intersection / min-wall / overhang / dimension-chain) plus a post-export re-read check. Activate when user says: 改模, 改尺寸, 孔做大点, 填孔, 掏空, 倒角, 'make it 5mm longer', 'enlarge the hole to M4', 'the downloaded part doesn't fit', or any edit of an existing mesh."
version: "0.7.0"
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

用户一句话 → L1 意图解析 → 单步 CSG 操作 → 五道门校验 + 导出回读 → 报告

**核心场景**：下载的挂架差 5mm 卡不进 / 「这个孔做成 M4」/ 「太厚了掏空省料」。
与 makerworld-search 互通：找到模型 → 本 skill 改好 → 下游打印 skill 切片打印
（如已安装同系列打印编排 skill）。

**架构原则**：manifold3d 是几何后端（布尔永不产生坏网格），
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
   - 自动输出 JSON 报告（op / pass / meta / gates / export_check）
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
| 填孔（全部 / 只填 ≤ 某直径） | `fill part.stl -o out.stl` ｜ `fill part.stl --dia 4 -o out.stl`（`--dia-max` 同义） |
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

**drill 口径**：`--through` 时 `--at` 只取 x,y（孔轴横向位置），轴向坐标忽略；
`--depth` 时 `--at` 是**孔口表面点**，孔沿 -Z 向材料内钻 `--depth` 深
（`--at 30,20,4 --depth 2` → 孔占 z=2..4）。钻空了（没碰到材料）脚本会报错并提示，
不会静默输出原样文件。

## L1 意图解析协议（agent 必读）

0. **先锁口径再动手（2026-09-04 翻车修正）**：fit/改模需求开工前，必向用户
   复述并确认四件事——①对象真实尺寸（能实测就实测，别用名义值）；②「放下」的
   语义（坐进内腔底面 / 全包围 / 靠背托底——语义不同则件型完全不同，做错即
   「完全不可用」）；③余量策略（FDM「刚好」= 每边 +0.3mm 插入余量，100×100
   方物 → 内腔 100.6×100.6，精确 100.0 是放不进去的）；④硬约束清单（如 SKÅDIS
   挂装接口 40mm 网格必须保持）。用户要求重新描述需求 = 旧交付物作废、新口径
   全权，别为旧方案辩护。

**改模铁律（两条都踩过坑）**：

① **改模 ≠ 建模**。「改模承诺 = 在真实下载件上做修改」。从零参数化重建只是
   兜底中的兜底——重建件的结构语言（挂钩形态/镂空位置/公差风格）不等于原作，
   用户一眼识破（「这不是在那个模型基础上改的」）且大概率不可用。

② **下载不到原件 → 直接向用户要文件，并且一开始就说清楚**。下载路径全部
   试尽（MW 登录墙 / CDN 401 / CF 挑战 / GitHub 镜像）仍拿不到时，**立刻
   明说「我拿不到原件，需要你下载后发我」，同时停下等待**——不要转入
   从零重建然后装作完成了需求。用户反馈很直接：做不到就说做不到，别做
   无用的尝试浪费 token。半途告知也比沉默重建强：分析原作设计语言期间就应说
   「无法下载原件，方案 A 等你给文件 / 方案 B 按图片分析重建（有偏差风险）」让用户选。

③ **拿到原件后：先解剖再动刀**。切片剖面族（ASCII 可视化）+ contains 射线
   实测内腔/壁位/挂槽坐标，画出结构图后再定修改方案；动刀优先 boolean 手术
   （劈半平移/挖腔/填补）而非重造。每个手术步骤后跑一扇验证门（位置/尺寸/
   水密/单件），全绿才交付。

1. **单位永远是 mm**，M 系螺丝孔径 = 螺纹公称 + 0.2（M3→3.2，M4→4.2，M5→5.2）
2. **「改尺寸」默认问清**：整体缩放还是只改一维？改完的孔要不要保原径？
   —— 默认 `--keep-holes`，因为 99% 的场景是「下载件差一点」，孔是要配螺丝的
3. **「厚一点/薄一点」**：加厚用 thicken（外扩），薄用 shrink（切短）或 hollow（掏空）
4. **「倒角/圆角」**：round-edges 自动保孔（先填→closing→重钻），无需用户提醒。
   ⚠️ 语义边界：closing（腐蚀∘膨胀）只平滑**凹**特征，凸边数学上不动——
   凸边倒圆需真 fillet 路径，报告时别声称「外缘已倒圆」
5. **轴向不明必问**：x/y/z 还是「沿孔的方向」？info 先看孔的 axis 字段
6. **改完必报告**：五道门结果 + 最终尺寸链 + 与用户要求的误差（G5 的 error_mm）
   + G1 的 through_holes_genus（保孔类操作会校验通孔数不变）
7. **「放得下 X」= 内腔需求，不是外廓**：resize --size 是外廓尺寸。换算 = 内 + 2×壁厚 + 1-2mm 活动量
   （FDM 单边活动量 0.3mm 起步）。封闭容纳超床时（外廓 > 床容量）**主动给出开放端摇篮方案**
   （见 references/long-object-design.md），别硬缩破坏用户需求。
   **fit-interior 四步协议（2026-09-04 真实件全链验证）**：
   ① 开放腔实测 = 切片内环 + 射线序列（decompose 假分量陷阱见 references/manifold-notes.md），斜底件另扫底面 z 分布
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
| G1 watertight | 非流形/漏水网格 + **通孔数（genus）不变**（保孔类操作校验） | 基本不会挂（CSG 后端保证）；genus 变了 = 保孔断裂，查 references/manifold-notes.md |
| G2 self-intersect | 自相交 | 同上，tripwire 性质 |
| G3 min-wall | 壁厚 < 0.8mm（FDM 最小壁） | 真风险：打印会软/断。报告数值，用户坚持就照打（0.4 也能打，就是脆） |
| G4 overhang | >45° 悬垂超 5% 面积 | 提示开支撑或调向；盲孔顶面是常见触发源，属预期内 |
| G5 dimensions | 尺寸链 vs 要求（>0.1mm）或超打印床 | 看 error_mm：超床必失败，其他数值报告给用户 |

另有 **export_check**（导出回读）：每次写操作落盘后重新 load 交付文件，
核对单 body 数、watertight、体积对账（<0.5%）——kernel 内正确 ≠ 磁盘文件正确，
任一不符则 pass=false。**关键语义**：G3/G4 挂 ≠ 拒绝输出——文件照常导出，
exit code 2 提示 agent。薄壁和悬垂是**用户的决策空间**，agent 的职责是把数值摆出来。

## 实测战绩

- **合成件回归（plate 60×40×4 + 4×M3.2 孔，2026-09-03 起，2026-09-13 全量重跑于 manifold3d 3.5.3）**：
  resize 1.2× + keep-holes → 72×48×4.8 精确、孔径 3.2 保住、genus 4 全保，五门+回读全绿；
  反例 hollow wall 0.4 → G3 精确拦截。⚠️ 2026-09-13 体积/genus 对账曾抓出旧版
  「保孔只保半截」的静默 bug（重钻圆柱按中心假设平移），已修——**保孔验证必须看
  genus，不能看 holes_detected**（盲坑也会被算成孔）
- **真实件端到端（2026-09-03 可行性验证，GitHub 下载 SKÅDIS Bin 80×50×80）**：
  下载→info→resize 全链跑通，G5 两次精确拦截超床件（270 外廓 fits_bed=false）；
  45° 斜放数学推演推翻最初的方案，最终交付开放端摇篮 250×15×120（五门全绿，
  166g PLA）——床容量推演方法论沉淀在 `references/long-object-design.md`

> 完整调试坑位表（cylinder 原点语义 / 共面贴合不焊接 / decompose 幽灵腔 /
> SKÅDIS 挂接逐点复刻参数等）已迁至 **references/manifold-notes.md**，
> SKILL.md 只保留索引。改任何几何代码前先读它。

## References

- `references/manifold-notes.md` — 工程实测笔记全案（manifold3d 绑定行为 / 布尔与形态学 /
  trimesh 交互 / 内腔解剖 / SKÅDIS 挂接参数 / 3MF 交付）。**改几何代码前必读**
- `references/long-object-design.md` — 长物收纳的床容量推演链（封闭方案全灭的数学）+ 开放端摇篮已验证设计（260×100 案例）+ 下载件结构判别法
- `references/fit-interior-case.md` — 「刚好放下 X」全链案例（2026-09-04）：SNS 敞口筐改 SKÅDIS 原生直挂 100×100 方物收纳。含口径锁定协议、下载通道实测（CF 封锁时 gh api Contents API base64 兜底）、开放腔三信号解剖协议、逐轴缩放链+壁厚后果、SNS vs SKÅDIS 挂装体系判别、fit-interior op 设计草案（未实现，晋升需跑回归）
- `references/base-model-download-sources.md` — 底模下载源矩阵与绕行实测（MW 登录墙 / TV CF 按天概率与隔天重试 / GitHub 镜像 gh api 路线 / 已知可用 SKÅDIS 仓库清单）
- `scripts/make_test_plate.py` — 回归测试件生成器（60×40×4 + 4×M3.2，参数可调）——回归不依赖外部仓库
- `scripts/render_stl.py` — STL 双视角 PNG 渲染（matplotlib Lambert 光照，无需 Blender/视觉模型；中文字体已适配 WSL / Windows 原生 / macOS）——「改好发用户看看」的固定出口
- `examples/` — 案例复盘脚本（一次性实验，硬编码路径，不可直接运行，只作方法论参考）

## 与其他 Skill 的接口

- 上游 **makerworld-search**（同系列，如已安装）：搜到模型 → 下载 → 本 skill 改
- 下游打印编排 skill（如已安装）：改好的模型 → preview / slice / 打印；AMS 多色 → colorize
- 改不了（自由曲面变形类需求）→ 征询用户走生成兜底（Tripo/Meshy 类服务）

## 回归场景（任何代码改动后必须重跑）

```bash
# 先生成测试件（本仓库自带，无外部依赖）
python3 scripts/make_test_plate.py -o plate.stl
```

最小回归集，每条对应一个曾修过的 bug 类：

| 场景 | 命令 | 验证点 |
|---|---|---|
| resize 保孔（核心场景） | `resize plate.stl --factor 1.2 --keep-holes -o t.stl` | exit 0；G1 through_holes_genus=4（**不看 holes_detected**）；体积 ≈ 72×48×4.8 − 4×π×1.6²×4.8 |
| 低分段孔检测 | `info plate.stl` | holes_detected=4（tier A 路径） |
| 填孔齐平 | `fill plate.stl -o t.stl` 后 `info t.stl` | holes_detected=0，genus=0，无凸起 |
| 盲孔口径 | `drill plate.stl --at 30,20,4 --dia 8 --depth 2 -o t.stl` | 孔占 z=2..4（孔口语义），removed_mm3 ≈ π×4²×2 |
| 钻空拦截 | `drill plate.stl --at 100,100,2 --dia 4 --through` | 报错「hole misses the material」，不输出文件 |
| 倒角保孔 | `round-edges plate.stl --radius 1.5 -o t.stl` | genus=4 保留，五门+回读全绿 |
| minkowski 网格完整性 | `thicken plate.stl --by 1 -o t.stl` | G1 watertight=true（process=False 回归） |
| 反例门拦截 | `hollow plate.stl --wall 0.4 -o t.stl` | G3 fail，min_wall≈0.4，exit 2 |
| 尺寸链 | `extend plate.stl --axis z --by 8 -o t.stl` | G5 z=12 精确；延伸体继承通孔 |
| 3MF 交付 | 任一 op 输出 `.3mf` | `<build><item>` 存在（旧版 trimesh 由 `_patch_3mf` 补写） |
| 参数校验 | `resize --size 40x20` / `drill --at 30,20` / `cut --at z=99` | 均报错并给正确用法示例 |

**fit-interior 相关回归（草案期只做协议级验证，op 落地后升级为命令回归）**：
- 开放腔解剖：三信号（切片环/射线/体积验算）互证，布尔差分量仅作参考必弃核
- 口径锁定：内腔/外廓/深度/挂装体系四要素缺一先问，超时默认+显式告知

**环境注意**：Windows 原生环境用 `python`（无 `python3` 别名）；依赖安装
`pip install "manifold3d>=2.4,<4" trimesh numpy scipy rtree lxml`（scipy 缺失时孔检测
禁用并有 stderr 警告，lxml 仅 3MF 导出需要）。manifold3d 版本行为有差异，
**不要解除版本 pin**。