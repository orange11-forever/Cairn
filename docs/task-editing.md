# 任务编辑与依赖

在「项目任务」选择项目后，可创建任务、打开任务详情，编辑标题、描述、负责人、优先级、截止时间和验收标准。负责人来自当前组织中启用且可读取该项目的成员；候选按页加载，不公开邮箱或提供方身份。截止时间按浏览器本地时区填写，保存为带时区时间；可明确选择未分配和无到期时间。只读成员可查看详情与前置依赖。

任务以 `revision` 防止覆盖其他人的更新。创建时为 1；成功编辑、状态转换、前置依赖新增或删除后递增。编辑必须提供 `expectedRevision`。状态和依赖新增保留旧请求兼容性，新界面始终发送当前修订号。版本过期返回 409 `revision_conflict`；界面保留草稿，并提供「重新读取最新版本（替换草稿）」。保存已成功而刷新失败时，界面单独提示并暂停继续写入；重试刷新不会重复创建任务。

| 操作 | 接口 | 成功响应 |
| --- | --- | --- |
| 详情 | `GET /api/v1/tasks/{task_id}` | 200 TaskResponse |
| 编辑 | `PATCH /api/v1/tasks/{task_id}` | 200 TaskResponse |
| 负责人候选 | `GET /api/v1/projects/{project_id}/assignees` | 200 `{items,nextCursor}` |
| 前置依赖 | `GET /api/v1/tasks/{task_id}/dependencies` | 200 `{items,nextCursor}` |
| 添加依赖 | `POST /api/v1/tasks/{task_id}/dependencies` | 201 DependencyResponse |
| 删除依赖 | `DELETE /api/v1/tasks/{task_id}/dependencies/{dependency_id}?expectedRevision=N` | 204，无正文 |

PATCH 必须至少包含一项可编辑字段，拒绝额外字段和直接修改状态。显式 null 清空描述、负责人、到期时间或验收标准；未提供的字段保持原值。标题去除前后空白后为 1–240 字符，描述和验收标准最多 10000 字符。优先级为 low、medium、high 或 critical。状态继续使用原状态机，依赖必须位于同一项目且不得成环。

候选和依赖页默认 50 项，范围 1–100。游标绑定用途、组织和项目或任务；候选还绑定请求者。无权限与不存在均按项目隐匿规则返回 404；错误体统一为 `{code,message,traceId}`，与 X-Request-ID 关联。任务和项目 HTTP 响应带 `private, no-store` 与 `nosniff`，SSE 保持原事件缓存语义。

同一组织的任务写操作以组织行锁序列化，再按项目、当前成员与用户、任务及分配目标的顺序重验权限。该顺序与成员角色变更协调，防止跨项目相反负责人分配形成锁反转；吞吐量以当前个人和小团队场景为目标。业务更新、修订号、Audit 和 Outbox 在同一事务提交，冲突或失败没有残留写入。迁移 0013 将历史任务修订号设为 1；已有非空负责人或修订号大于 1 时，降级明确拒绝丢弃数据。

任务编辑与依赖管理已扩展[阶段、里程碑和项目修订](project-structure.md)：任务创建与编辑可设置或清空所属阶段、里程碑；涉及归组的 PATCH 必须同时携带任务与项目修订号。原有六字段编辑请求仍兼容。阶段和里程碑支持归档与恢复；真实任务节点图及规划确认应用已接通。


## 明确确认的助手操作

项目页的「助手项目操作」使用当前个人助手所选模型，将用户本次明确输入转换为一个待确认动作。预览只读取完整项目结构与助手指导，不检索资料正文；任务描述、指导或资料中的指令不授予写入权限。模型仅输出白名单结构化建议，不能调用工具或直接写入。首版每次执行一个动作；意图不清或涉及多个动作时提示补充说明。

支持 `create_task`、`update_task`、`change_status`、`add_dependency`、`remove_dependency`。创建仅接受标题、描述、优先级、验收标准及已有阶段/里程碑；初始状态为 backlog，负责人和到期时间留空。字段调整一次修改 title、description、priority 或 acceptanceCriteria 中一项。状态机、归组约束与依赖防环沿用现有任务服务。

| 操作 | 接口 | 响应 |
| --- | --- | --- |
| 生成只读建议 | `POST /api/v1/projects/{project_id}/operation-preview`，`{intent}` | 200，完整快照、单动作及 canExecute |
| 确认执行 | `POST /api/v1/projects/{project_id}/operations`，`{operationId,confirmed:true,preview}` | 首次201，重放200 |
| 我的已执行记录 | `GET /api/v1/projects/{project_id}/operations?cursor=…&limit=10` | 200，`{items,nextCursor}`，limit范围1–20 |
| 查询操作结果 | `GET /api/v1/projects/{project_id}/operations/{operation_id}` | 200，已保存动作和结果；不存在404 |

生成与执行均要求有效会话、精确 Origin/CSRF；只读项目成员可预览，确认执行重新要求 WRITE。执行在组织与项目锁下复核完整结构快照，再调用任务服务的事务内写逻辑。实体更新、修订号、审计、Outbox及操作记录在同一事务提交，失败全部回滚。旧快照返回409 `project_analysis_changed`；同一组织、项目、发起者和operationId的同内容提交返回原结果，不同内容返回409 `operation_conflict`。预览由客户端显式确认提交，不是服务端签名的授权凭证。

成功记录默认只有发起者在仍可读取项目时可查；实际任务按项目权限共享。仅保存用户要求、动作、说明与执行结果，不保存助手私有指导或项目快照副本；未成功的请求返回原有错误体与请求编号。迁移0022拒绝降级删除非空操作表。

网页在确认前保存操作编号；结果未知时暂停新的提交，先查询原编号，必要时仅重发同一份请求。刷新页面后仍可查询该编号。执行成功后刷新列表、节点图、结构以及已打开任务详情/依赖；刷新失败单独提示「操作已执行」，重新读取不重复执行。外部真实厂商模型验收仍由部署者完成，受控模型测试不代表真实厂商连通。


## 工作量与工期情景

任务创建和编辑增加 `estimatedEffortMinutes`、`remainingEffortMinutes`，为可空的非负整数分钟，上限2147483647。未填写表示未知，显式0表示没有工作量；剩余量可以超过初始估算。Web使用人时输入，乘60后四舍五入保存为整分钟，留空保存null。编辑继续使用任务revision、原事务与Audit/Outbox，0剩余量不会自动把实际任务标为done。

`PATCH /api/v1/projects/{project_id}/capacity` 接收 `{expectedProjectRevision,dailyCapacityMinutes,workingWeekdays}`。每日产能为整个项目每天可投入的总人时，服务端按整数分钟保存，可为null或0；两种情况均不输出情景日期。周历使用ISO编号：1=周一至7=周日，须为非空、无重复数组，默认 `[1,2,3,4,5]`。此接口要求当前WRITE及Origin/CSRF，项目版本过期返回409 `revision_conflict`，成功递增项目revision，设置、审计和Outbox在同一事务保存。

`GET /api/v1/projects/{project_id}/schedule-scenario?startDate=YYYY-MM-DD` 要求READ，只接受纯日期。复用节点图的组织→项目锁与完整任务/依赖读取，上限1000个任务、5000条依赖，超限422，不返回局部项目的预测。响应包括读取时间、项目revision/产能/周历、完整任务ID/标题/revision/实际状态/优先级/创建时间/初始估算/剩余量、完整依赖、缺口、警告、已知剩余分钟，以及可复算的排程与假设。此接口不调用AI，也不修改或持久化任务和情景。

计算采用单通道串行规则：项目总产能集中在一个依赖已满足的任务；ready任务按critical→high→medium→low、createdAt、UUID稳定排序，任务完成后日内剩余产能继续用于下一个任务。返回每项相对开始的工作分钟offset及开始/结束日期。非工作日开始日期顺延；日历以完整周跳跃换算，不逐天遍历长工期。正工作任务的结束日期使用 `(endOffset-1)//dailyCapacityMinutes`：周一8小时任务周一结束，下个正工作量任务周二开始。跟在周一整日结束处的0工作量任务，开始/结束均为周一，offset不增。超出0001–9999年范围时列出date_out_of_range缺口，不输出部分日期或抛出500。

最长依赖链单独累加剩余分钟，除以日产能得到理论工作日下界；它忽略独立任务对共享产能的争用，不能替代串行资源完成日期。例如两个互不依赖的8小时任务、项目每日8小时，依赖链下界为1个理论工作日，串行资源需要2个工作日。下界不生成另一份完成日期。

实际done任务按0处理而不改写记录字段，cancelled任务排除工作量；未完成任务依赖cancelled前置时，该依赖不视为满足。任何未完成任务缺remaining、blocked没有解除日期、取消前置或产能缺失/0时，整个项目不返回完成日期、任务日期或关键链；仍展示实际状态和已知工作量。缺estimated只警告，不阻断使用剩余量计算；不生成伪加权完成率。

情景仅使用周历，不包含节假日、成员差异或自动预测阻塞解除。网页在项目revision变化、项目刷新或开始日期变化时隐藏旧情景，用户显式重算；计算中迟到的旧revision响应不能覆盖较新的项目缓存。迁移0023保留既有项目与任务，历史工作量/产能为空、周历为周一至周五；已有工作量、产能（含0）或非默认周历时拒绝有损降级。
