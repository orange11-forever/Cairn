# 项目结构与任务归组

阶段和里程碑位于项目任务区域上方，使用内联表单创建与编辑。成员、owner、admin可见写入口，viewer保留读取；每次请求仍按当前成员身份和项目 ACL 验证权限。

阶段包含名称（1–120字符）和排序位置（JSON整数，0–2147483647）；按位置、ID分页。里程碑包含名称（1–160字符）、说明（最多4000字符）、验收标准（最多10000字符）、带时区的截止时间和可空所属阶段；按创建时间、ID分页。两个列表使用 `items` / `nextCursor`，`limit` 为1–100，游标最多2048字符且绑定组织、项目和资源类型。界面提供加载后续页入口，包括任务归属选择器。

| 操作 | 路径 | 写入版本 |
| --- | --- | --- |
| 列出 / 创建阶段 | `GET` / `POST /api/v1/projects/{project_id}/stages` | POST需 `expectedProjectRevision` |
| 编辑阶段 | `PATCH /api/v1/projects/{project_id}/stages/{stage_id}` | `expectedProjectRevision`、`expectedRevision`、至少一个可编辑字段 |
| 列出 / 创建里程碑 | `GET` / `POST /api/v1/projects/{project_id}/milestones` | POST需 `expectedProjectRevision` |
| 编辑里程碑 | `PATCH /api/v1/projects/{project_id}/milestones/{milestone_id}` | `expectedProjectRevision`、`expectedRevision`、至少一个可编辑字段 |

所有修订从1开始。项目读取和列表输出真实 `revision`；公开SDK保留可选字段以兼容旧项目响应，结构界面必须取得真实版本才允许保存。成功创建为201、编辑为200；结构或任务版本陈旧返回409 `revision_conflict`。界面保留输入，不自动重试；用户点击“重新读取项目结构（替换草稿）”后才替换草稿与恢复写入。取消冲突表单也不会恢复陈旧版本写入。

任务创建、PATCH、读取和列表提供 `milestoneId`，PATCH也提供 `stageId`；省略保持原值，显式null清空。任务绑定里程碑时，任务阶段必须与该里程碑所属阶段一致，不匹配返回422 `invalid_grouping`。跨组织、跨项目或不可见引用返回404。修改里程碑阶段若将破坏已绑定任务的归属，则返回409 `milestone_in_use`，需先调整任务，服务端不会批量移动任务。

旧任务创建、状态和依赖请求兼容原调用者；创建允许可选 `expectedProjectRevision`。旧六字段任务PATCH仍需 `expectedRevision`，新增项目版本字段可选；任何包含 `stageId` 或 `milestoneId` 的PATCH必须携带 `expectedProjectRevision`，即使同时编辑标题等普通字段。新界面始终提交当前项目修订。阶段、里程碑、任务创建 / 详情编辑 / 实际状态转换、依赖添加 / 删除每笔成功业务事务将项目修订增加一次；失败、冲突、拒绝的重复操作不增加。数据、修订、Audit和Outbox同事务提交或回滚。

写入后界面刷新项目修订、结构列表和有关任务；已提交而刷新失败单独提示，禁用后续写入，用户明确重新读取后恢复。未修改的截止时间保持服务器秒、小数精度和时区，未修改的空字符串也不被清空。切换项目或组织、会话失效会取消旧范围请求与草稿。

验证错误422、未登录401、不可见 / 越权404、CSRF403、数据库不可用503、未知异常500使用现有 `ErrorBody`。错误 `traceId` 与 `X-Request-ID` 一致，保留 `private, no-store`、`nosniff`、CORS和协议 `Allow`；结构写入先验证会话，再验证CSRF。新接口及生成OpenAPI、SDK和运行时schema同步。

阶段和里程碑还可通过原PATCH端点单独提交`archived`与两个修订号来归档或恢复；归档状态不能与普通字段编辑混合提交。归档要求先解除所有任务关联，阶段还需先归档其活动里程碑；占用返回409 `structure_in_use`。恢复里程碑时会重新检查所属阶段可用性。归档保留历史，不删除数据，归档对象不能被继续编辑或用于新任务归组。

删除、路线图、邮件 / 邀请和AI规划写入仍在后续范围。迁移0014为既有项目、阶段、里程碑增加revision=1，保留原字段，增加可空里程碑阶段与验收标准；0015增加归档状态，保留已有结构。复合外键约束同组织 / 同项目引用，相关降级拒绝丢弃已编辑或归档结构。
