# examples/

**Case-review scripts, not reusable tools.** These were one-off experiment
scripts from real disassembly sessions. They contain hardcoded personal
paths (`/home/<user>/.hermes/...`, `/tmp/feas/...`) and will not run as-is
anywhere else — treat them as *readable walkthroughs* of the disassembly
methodology (ASCII slice families, ray probes, contains scans), and adapt
paths locally if you want to replay them.

- `extract-mount-params.py` —解剖真实 SKÅDIS 配件的挂装接口（切片族 + 射线探针 + 法向平面提取），输出一手挂装参数
- `fit-interior-case-skadis-bin.py` —「刚好放下 X」全链案例（SNS 筐 → SKÅDIS 直挂收纳）的执行脚本复盘

The reusable CLI is `scripts/remodel.py`; the regression fixture generator
is `scripts/make_test_plate.py`.