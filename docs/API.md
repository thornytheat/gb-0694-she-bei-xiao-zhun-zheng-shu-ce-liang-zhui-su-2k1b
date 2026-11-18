# 接口

`POST /api/run`：JSON中的csv文本，省略使用样例；或multipart字段file。最大5MB。传 `{"sample":"edge"}` 运行量程边缘样例。

`POST /api/m1`至`POST /api/m7`：独立运行到指定模块，JSON结构同运行接口。

`GET /api/history`：历史批次。`POST /api/review`接收id、revision和decision（通过或退回）。`GET /api/evidence.csv`提供单一证据导出。

`POST /api/retest`：补交待复测记录的读数、误差带与测量日后重判。请求体：

```json
{"id":"批次号","cert":"E002","line":4,"value":"9.995","error":"0.002","measured_at":"2026-11-17"}
```

- `cert` 必填；同一证书有多条记录时必须带 `line`（原始行号）。
- `value`、`error`、`measured_at` 三项都必须补交。`value` 与 `error` 默认按伏特解释；可用 `value_unit` / `error_unit` 显式指定（V、mV、µV）。
- 返回重判后的整批数据、`decision_record`（本次裁决）和 `reused`。同一份补交重跑返回同一 `decision_id` 且 `reused` 为 true，不新增裁决。
- 已完成重判的记录再次补交（内容不同）返回 422 `NOT_PENDING`。

结构错误422，版本变化409，文件过大413，批次或记录不存在404；错误返回code与message。所有页面可从左侧七个模块入口访问。

`GET /api/runs/<id>`读取指定批次；页面与证据CSV通过run_id查询参数绑定批次，模块导航保留该参数。返回体中的 `verdicts` 是叠加补交裁决后的有效结论，`original_verdicts` 保留原始结论，`pending_retests` 列出仍待复测的记录，`retest_rows` 是补交裁决存档。

JSON请求体必须是对象，数组、标量、null、损坏JSON及错误上传字段返回400，且不运行默认样例。
