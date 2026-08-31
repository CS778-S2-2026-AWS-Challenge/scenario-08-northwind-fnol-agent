# Sprint 2 第一周个人工作安排

来源：[`sprint2-week1-kanban-draft.md`](sprint2-week1-kanban-draft.md)

- 周期：2026 年 8 月 17 日至 21 日
- 工作量：每人每天 8 小时，全周 40 小时
- 本周目标：五个人按技术栈并行推进，使清晰报案、材料待补与恢复、人工转接、专业复核和员工处理五条路径具备可运行基础，并为第二周的端到端整合做好准备。

## `Ysoseri1224`：Claimant 前端与 Agent 行为

- **Day 1：**建立清晰报案、人工请求和紧急情况的 Claimant/Agent 行为基线。
- **Day 2：**实现对话式报案、可纠正表单，以及材料待补后的继续办理和会话恢复。
- **Day 3：**完成主动转人工、紧急中断和 policy 模糊时的 Agent 权限边界。
- **Day 4：**连接 Claimant UI 与 Agent controller，使普通、待补材料和转人工路径使用统一 Claim State。
- **Day 5：**演示并修复 Claimant 主要路径，交叉检查人工转接和专业复核结果。

## `liyang6620`：后端 API 与 AWS 接入

- **Day 1：**确定 claim creation、policy/history 和 AWS 服务的 API 与 adapter 边界。
- **Day 2：**实现 claim 创建、路由、材料上传和 session 恢复 API，并保留 AWS fallback。
- **Day 3：**实现 handoff 和 policy/history retrieval API，处理服务不可用和超时情况。
- **Day 4：**连接后端 API、可用 AWS adapter 和 fallback，使外部失败不会丢失 claim 状态。
- **Day 5：**验收创建、路由、handoff 和 AWS/API 行为，并确认第二周所需接口。

## `jxu316-arch`：持久化、Session 与 Policy/History 数据

- **Day 1：**确定 Claim State、session、revision、恢复和 policy/history 数据映射。
- **Day 2：**实现 claim/session repository，支持保存、更新、冲突检查和跨会话恢复。
- **Day 3：**实现 handoff ownership、policy/history 来源和专业复核记录的持久化。
- **Day 4：**统一 claim、session、handoff、review signal 和 staff write-back 的 revision。
- **Day 5：**验收恢复、专业复核和状态回写数据，检查各路径是否使用同一 Claim State。

## `LLL263`：Staff Workbench、Handoff 与状态回写

- **Day 1：**建立 staff 队列、handoff card 和 assign/review/resolve 状态回写基线。
- **Day 2：**实现已创建、已路由和材料待补案件的员工视图与下一步操作。
- **Day 3：**实现紧急转接、人工请求和专业复核的队列、详情与处理动作。
- **Day 4：**连接 staff queue、案件详情、接管、复核和 Claimant 状态更新。
- **Day 5：**验收 handoff、专业复核和 write-back，确认内部信息不会暴露给 Claimant。

## `bdfa123`：Evidence/Media 与 Fixture 基础设施

- **Day 1：**建立材料生命周期、可见性规则和五条业务路径的 fixture 基线。
- **Day 2：**实现图片/PDF mock storage、材料 metadata 和 proposed/confirmed 等状态转换。
- **Day 3：**建立 handoff evidence packet，以及 policy 模糊、证据冲突和数据不可用场景。
- **Day 4：**让各条路径共用 evidence fixture service，并检查材料状态和可见性问题。
- **Day 5：**交叉验收各路径的 evidence，整理第二周需要继续整合的 fixture 和问题。

## 五天推进关系

| 日期 | 全组推进结果 |
| --- | --- |
| Day 1 | 各技术栈建立共同业务路径所需的模型、接口和 fixture 基线 |
| Day 2 | 清晰报案及材料待补/恢复路径形成可运行模块 |
| Day 3 | 人工转接、紧急情况、policy/history 和员工处理能力形成可运行模块 |
| Day 4 | 每个人在自己的技术栈内连接五条路径，并补齐失败和可见性状态 |
| Day 5 | 由其他成员参与验收、修复问题，并明确第二周端到端整合的输入 |
