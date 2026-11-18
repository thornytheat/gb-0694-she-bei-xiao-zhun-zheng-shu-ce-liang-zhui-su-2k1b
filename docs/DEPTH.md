# 深度登记 设备校准证书与测量追溯

- 规模：中型
- 使用者与工作流：检验机构质量员，合并仪器使用与校准证书，裁决测量是否在有效可追溯链内。
- 核心规则：证书有效期与量程双约束；参考标准也须在校准时有效，证书撤销向下游传播并检测环。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 证书接收 | 运行证书接收并复核证据 | `POST /api/m1`；`/work/1` | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py` |
| M2 设备别名 | 运行设备别名并复核证据 | `POST /api/m2`；`/work/2` | `app/modules/m2_identity/rules.py` | `tests/test_m2.py` |
| M3 有效区间 | 运行有效区间并复核证据 | `POST /api/m3`；`/work/3` | `app/modules/m3_validity/rules.py` | `tests/test_m3.py` |
| M4 量程匹配 | 运行量程匹配并复核证据；带单位误差带越界时标为待复测 | `POST /api/m4`；`/work/4` | `app/modules/m4_ranges/rules.py`、`app/domain.py` | `tests/test_m4.py`、`tests/test_band.py` |
| M5 溯源链路 | 运行溯源链路并复核证据 | `POST /api/m5`；`/work/5` | `app/modules/m5_trace/rules.py` | `tests/test_m5.py` |
| M6 测量裁决 | 运行测量裁决，区分可采用/拒用/待复测，补交后重判 | `POST /api/m6`；`/work/6`、`POST /api/retest` | `app/modules/m6_verdict/rules.py`、`app/retest.py` | `tests/test_m6.py`、`tests/test_retest.py` |
| M7 撤销复核 | 运行撤销复核并复核证据 | `POST /api/m7`；`/work/7` | `app/modules/m7_revocation/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码证书 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py::test_legacy_chinese` |
| TRAP-07 | 空值测量 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_missing_isolated` |
| TRAP-08 | 设备编码保形 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_device_code_preserved` |
| TRAP-14 | 定义冲突 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_conflict_certificate_flag` |
| TRAP-20 | 溯源依赖环 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m5_trace/rules.py` | `tests/test_m5.py::test_reference_cycle` |
| TRAP-22 | 设备别名 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_alias_order_independent` |
| TRAP-23 | 失效日边界 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_validity/rules.py` | `tests/test_m3.py::test_expiry_endpoint` |
| TRAP-25 | 多证书重叠 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_validity/rules.py` | `tests/test_m3.py::test_overlapping_certificates` |
| TRAP-26 | 读数在界内但误差带跨界 | 只看读数误收 | 标为待复测，不直接采用也不整批退回 | `app/domain.py`、`app/modules/m4_ranges/rules.py` | `tests/test_band.py::test_reading_inside_but_band_outside_is_retest` |
| TRAP-27 | 误差带缺单位或单位冲突 | 当作纯数字误判 | 隔离并给出 `BAND`/`BAND_UNIT` 原因码 | `app/domain.py`、`app/modules/m2_identity/rules.py` | `tests/test_band.py::test_bad_band_is_quarantined` |
| TRAP-28 | 补交重跑重复裁决 | 每次补交新增裁决 | 确定性裁决ID，重跑不新增 | `app/retest.py`、`app/store.py` | `tests/test_retest.py::test_duplicate_resubmission_does_not_add_decision` |
| TRAP-29 | 补交写入中断 | 半条裁决或丢失补交 | 单事务写入，重试恢复 | `app/store.py` | `tests/test_retest.py::test_crash_between_judge_and_commit_recovers` |

## 对账规则

输入记录 = 采信记录 + 隔离记录 + 相同行重复。重复表头与空行单独记数。业务合计按阶段中的守恒或差值列复核。运行清单有原文SHA256、规则版本与耗时；相同规则版本下同文重复提交复用批次。

## 已知不覆盖

部署为本地单用户工具，不连接外部上游系统。CSV单文件5MB及一万条业务记录上限；不推断未提供的未知数据。
