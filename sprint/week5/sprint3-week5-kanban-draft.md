# Sprint 3 Week 5 Kanban Card 草案

## 使用规则

- **周期：** 2026 年 8 月 31 日至 9 月 4 日。
- **正常容量：** 5 人 × 5 天 × 8 小时 = 200 人时；每人每天的正常 card 合计 8 小时。
- **估算：** 2–4 小时是常用范围；5 小时只用于边界清楚、可以完整验收的小型端到端功能。超过 5 小时必须拆卡。
- **多人 card：** 表示共同交付同一个结果。每个 assignee 都必须有明确的实际实现或文档产出，并分别计算工时；第二位负责人不是只做验证。
- **Review card：** review 是工作时间，但单独建 1–2 小时的小卡。一次 review 可以覆盖多个相关功能，交付物是复现结果、问题记录或通过结论。
- **推进方式：** `motor`、`home`、`contents` 三条 VP 代表性验证线每天并行；它们不是产品范围限制。
- **运行方式：** 运行时优先真实连接可用服务；fixtures 只用于测试、回归和离线验证，不用于伪装运行时成功。
- **语言：** 本文件是中文内部草案；确认后再翻译为英文并创建到 Kanban。

## 栈级负责人

| 成员 | 主要责任 |
| --- | --- |
| `Ysoseri1224` | 独立负责 Agent 行为与提示词、分支判断和动作选择；claimant 前端调性、UX、UI 重构；动态表单和客户侧隐私/共享状态；负责状态机的 Agent 行为部分 |
| `liyang6620` | 数据层、RAG、结构化业务数据、provider adapter、AWS/云端连接；Control Plane 的配置和数据模型 |
| `jxu316-arch` | 后端 domain、Claim Context、session/evidence/handoff 持久化与恢复；消费已批准的 Agent action contract；第三方 stakeholder 能力与服务契约；负责状态机的后端执行部分 |
| `LLL263` | Staff Workbench、队列、详情、staff 与 Agent 协作；staff 侧第三方状态和操作 |
| `bdfa123` | evidence/material 生命周期；第三方 service/adapter 的请求、结果验证、失败和重试 |

## Day 1：最小定义与首批可运行功能

Day 1 的定义只做到能立即支持实现。每个栈当天都要交付代码或可调用接口，不把所有时间用于讨论。

| 任务目标 | 工时分配 | 前置条件 | 可验收结果 |
| --- | --- | --- | --- |
| 定义三条线共用的 Agent action contract、动作含义和触发边界 | `Ysoseri1224 2h` | Sprint 3 总纲、现有 Agent 接口 | Agent 的询问、澄清、确认、推进、更新、交接和紧急升级都有明确触发与禁止条件 |
| 实现已批准 Agent action contract 到 Claim Context 的后端命令映射 | `jxu316-arch 2h` | Ysoseri1224 的 action contract、现有后端接口 | 后端只验证前置状态并执行/拒绝已提交动作，写入 revision 和事件，不决定 Agent 行为 |
| 重构 claimant 自然报案和确认/纠正界面 | `Ysoseri1224 3h` | 现有 claimant 页面 | 客户可提交自然语言、查看结构化理解并确认或纠正 |
| 实现动态表单的字段显示和状态提示 | `Ysoseri1224 2h` | 已注册字段、动作结构 | 页面能显示 proposed/confirmed/missing/pending 字段，不使用未注册字段 |
| 复现 Agent、claimant UI 和动态表单的首批路径 | `Ysoseri1224 1h` | 同日实现结果 | 一次 review 覆盖三个相关功能，记录可复现问题或通过结论 |
| 确定数据 provider adapter 的接口边界，并完成连接状态模型 | `liyang6620 2h + bdfa123 2h` | 现有数据配置、服务接口 | `liyang6620` 牵头并交付 adapter/config 接口；`bdfa123` 独立交付 service status/error 映射，两部分可以分别评审 |
| 建立 RAG/结构化查询的最小 API | `liyang6620 3h` | 数据边界 | 查询可返回结果、来源、时间和 unavailable/error 状态 |
| 定义并实现 Control Plane 首批配置读写接口 | `liyang6620 2h` | provider/config 字段清单 | 可读取和更新 provider、版本、启用状态等首批配置 |
| 复现 RAG、adapter 和 Control Plane 接口 | `Ysoseri1224 1h` | 同日实现结果 | 独立 review 覆盖三个相关接口，记录来源、错误和配置问题，不接手被评审功能的实现 |
| 实现 Claim Context 的 claim/session/evidence 基础保存和读取 | `jxu316-arch 3h` | 现有 domain/schema | 三条线可以保存和读取同一份 claim context |
| 实现 session resume 和 revision 基础接口 | `jxu316-arch 2h` | Claim Context repository | 新 session 能恢复未完成事项；旧 revision 不覆盖新状态 |
| 复现 Claim Context、resume 和 revision 基础接口 | `jxu316-arch 1h` | 同日实现结果 | 一次 review 覆盖三个相关后端功能，记录状态丢失或版本冲突问题 |
| 建立 staff Workbench 队列和 claim 详情骨架 | `LLL263 3h` | Claim Context 字段 | staff 能看到状态、缺口、责任方和下一步 |
| 在 Workbench 显示结构化上下文和第三方任务概要 | `LLL263 2h` | 第三方状态字段 | staff 不读完整聊天记录也能了解已确认事实和待处理外部请求 |
| 在 Workbench 显示第三方状态和可执行入口 | `LLL263 2h` | 第三方状态模型 | 可区分待授权、处理中、完成、失败、拒绝和待补信息 |
| 复现 Workbench 的队列、详情和第三方状态 | `LLL263 1h` | 同日实现结果 | 一次 review 覆盖三个相关页面状态并记录问题 |
| 建立 evidence/material API 和第三方任务状态映射 | `bdfa123 3h` | 现有 backend contract | 材料和请求有 claim 关联、来源、状态和时间 |
| 规定真实服务、不可用服务和测试 fixture 的入口隔离 | `bdfa123 2h` | service status 模型 | 正常运行不会读取隐藏 fixture 成功值；不可用状态可被前后端读取 |
| 复现 evidence API、第三方状态和入口隔离 | `bdfa123 1h` | 同日实现结果 | 一次 review 覆盖三个相关功能，记录失败或通过结论 |

**Day 1 容量：** 每人 8 小时，全组 40 小时。定义和实现同步完成，三条线均获得可继续开发的共同基线。

## Day 2：动态分支、持久化和管理配置

| 任务目标 | 工时分配 | 前置条件 | 可验收结果 |
| --- | --- | --- | --- |
| 定义并实现 Dynamic Form 的 Agent 分支判断 | `Ysoseri1224 2h` | Day 1 action contract、注册字段 | motor、home、contents 能根据已确认事实和缺失事项选择不同字段和下一步 |
| 持久化已批准 Dynamic Form 分支结果并映射到 Claim Context | `jxu316-arch 2h` | Ysoseri1224 的分支输出、Claim Context API | 后端保存字段、分支结果和 revision，不重新决定 Agent 分支 |
| 加入 claimant 侧 consent、共享范围和状态说明 | `Ysoseri1224 2h` | privacy 字段 | 客户能知道保存什么、共享给谁、为什么需要以及当前进度 |
| 接入 Agent prompt 的快速、引导和待补材料行为 | `Ysoseri1224 3h` | 动作结构、动态表单 | 已确认信息不重复追问；未来材料不阻塞无关的安全动作 |
| 复现动态表单、consent 和 Agent 行为 | `Ysoseri1224 1h` | 同日实现结果 | 一次 review 覆盖三个相关功能并记录问题 |
| 实现查询结果的来源投影和无结果处理 | `liyang6620 3h` | Day 1 RAG API | RAG、policy、history 查询用途和来源清楚；无结果不会生成假结论 |
| 实现 provider 选择和互斥运行配置 | `liyang6620 2h` | adapter/config 接口 | 一次运行只启用一个 provider，不混用 MongoDB、Cloudflare、AWS 数据 |
| 实现 Control Plane 配置读写与变更记录 | `liyang6620 2h` | Day 1 Control Plane API | 配置更新有版本、操作者和时间，可被运行时读取 |
| 复现查询、provider 切换和 Control Plane 配置 | `liyang6620 1h` | 同日实现结果 | 一次 review 覆盖三个相关接口，记录切换和错误问题 |
| 实现 claim/session/context 的完整保存和恢复 | `jxu316-arch 2h` | Day 1 repository | 用户跨 session 返回时能恢复同一 claim、form 和未完成事项 |
| 加入 revision 冲突和重复更新处理 | `jxu316-arch 2h` | persistence API | 旧客户端更新不会覆盖较新的 Claim Context |
| 将 evidence、handoff 和 next action 接入统一 context | `jxu316-arch 1h` | evidence/handoff 字段 | 三条线不维护私有材料或交接状态 |
| 复现保存、恢复和 revision 行为 | `jxu316-arch 1h` | 同日实现结果 | 一次 review 覆盖三个相关 persistence 功能 |
| 实现 staff 队列筛选和 priority/status 视图 | `LLL263 3h` | Claim Context、Workbench 骨架 | staff 可按状态、优先级、责任方和待处理事项查找 claim |
| 实现 staff 详情中的来源、缺口和下一步区域 | `LLL263 2h` | source/status 字段 | staff 能直接看到确认事实、来源、冲突和待补材料 |
| 实现 staff action 控件和状态回写入口 | `LLL263 2h` | handoff/action contract | staff 可接受、追问、确认或拒绝 Agent 建议 |
| 复现队列、详情和 staff action | `LLL263 1h` | 同日实现结果 | 一次 review 覆盖三个相关 Workbench 功能 |
| 实现第三方请求的准备、授权范围和发送记录 | `bdfa123 3h` | Day 1 service API | 请求包含 stakeholder、共享字段、授权、目的和当前 claim |
| 关联 evidence 与第三方请求及返回结果 | `bdfa123 2h` | evidence model | 返回结果有来源和验证状态，不直接写成 confirmed fact |
| 实现失败和重试状态 | `bdfa123 2h` | request state model | timeout/unavailable/retry 不丢失 Claim Context，也不会无意重复请求 |
| 复现请求、关联和失败重试 | `bdfa123 1h` | 同日实现结果 | 一次 review 覆盖三个相关 service 功能 |

**Day 2 容量：** 每人 8 小时，全组 40 小时。动态表单、持久化、Workbench、Control Plane 和第三方请求都已有第一批功能。

## Day 3：Agent 决策、真实服务和交接行为

| 任务目标 | 工时分配 | 前置条件 | 可验收结果 |
| --- | --- | --- | --- |
| 定义状态机中的 Agent 转换、动作选择和 Agent 侧失败边界 | `Ysoseri1224 2h` | Day 2 状态和动作 | 每个 Agent 转换明确触发条件、动作、提示词/工具调用和拒绝条件 |
| 实现状态机后端转换、持久化和失败处理 | `jxu316-arch 2h` | 已批准 action contract、Day 2 后端状态 | 后端明确验证前置状态、执行或拒绝动作、写入数据并返回失败原因 |
| 调优快速、复杂、紧急、人工请求和待补材料行为 | `Ysoseri1224 3h` | 状态机、动态表单 | Agent 能依据 Claim State 和用户状态选择不同动作；紧急情况不被普通流程阻塞 |
| 将 RAG/数据库工具调用接入 Agent 建议 | `Ysoseri1224 2h` | 查询 API、工具边界 | Agent 能引用来源并提出结构化建议，不直接越过运行时授权 |
| 复现 Agent 行为、工具调用和状态转换 | `Ysoseri1224 1h` | 同日实现结果 | 一次 review 覆盖三个相关功能并记录行为偏差 |
| 完成 provider adapter 的真实调用和错误投影 | `liyang6620 3h` | 可用 provider 访问 | 可用 provider 被真实调用；不可用 provider 明确返回限制 |
| 接入结构化 claim history 和 policy 查询 | `liyang6620 2h` | 数据 schema、来源规则 | 查询结果区分用途，并保留来源和时间 |
| 完善 Model Gateway 的 provider 配置和错误处理 | `liyang6620 2h` | 当前 `gpt-5.4-mini` 配置 | 当前模型可通过统一接口调用；自定义或不可用接口不会伪装成功 |
| 复现真实调用、查询和 Model Gateway | `liyang6620 1h` | 同日实现结果 | 一次 review 覆盖三个相关连接功能 |
| 实现 handoff、resume、evidence 和第三方任务的状态转换 | `jxu316-arch 2h` | Day 2 persistence | 接手、恢复和外部任务更新使用同一 revision |
| 记录 actor、reason、source、permission 和 consent 事件 | `jxu316-arch 2h` | event model | 关键状态变化可追溯，不把内部 signal 写入客户投影 |
| 定义第三方 stakeholder 能力、请求/响应字段和服务状态契约 | `jxu316-arch 1h` | 第三方服务边界 | 每类 stakeholder 的请求、等待、结果和失败状态有清楚边界；不定义 Agent 何时调用 |
| 复现 handoff、resume 和事件链路 | `jxu316-arch 1h` | 同日实现结果 | 一次 review 覆盖三个相关后端功能 |
| 实现 staff 接手、追问、确认/拒绝和写回流程 | `LLL263 3h` | handoff/action API | staff 接手后无需重复收集已确认信息，结果能写回 Claim Context |
| 显示第三方任务责任方、结果和待处理事项 | `LLL263 2h` | third-party state | staff 能判断下一步由客户、外部 stakeholder 或内部人员负责 |
| 加入 customer projection 和 internal signal 隔离 | `LLL263 2h` | visibility 规则 | 客户只看到适当状态，fraud/review 等内部 signal 不泄漏 |
| 复现接手、写回和信息隔离 | `LLL263 1h` | 同日实现结果 | 一次 review 覆盖三个相关 Workbench 功能 |
| 尝试连接已确认的第三方服务并实现对应 adapter | `bdfa123 3h` | 第三方 stakeholder、服务形式和访问条件的调研结论 | 有公开或测试访问条件时完成有限真实请求；没有企业访问权限时，按已确认的 form、请求字段、状态和结果形式实现明确标注来源的仿真，不伪装成真实连接 |
| 验证第三方返回结果与 evidence/claim 的一致性 | `bdfa123 2h` | evidence/result model | 不一致结果保持 proposed 或 review_required，不直接确认 |
| 完善 timeout、拒绝、未知结果和重试保护 | `bdfa123 2h` | request lifecycle | 未知结果保留上下文；重试不会重复产生业务动作 |
| 复现第三方连接、验证和失败保护 | `bdfa123 1h` | 同日实现结果 | 一次 review 覆盖三个相关 service 功能 |

**Day 3 容量：** 每人 8 小时，全组 40 小时。三条线都能从用户表达进入 Agent 判断，再进入下一安全动作、人工交接或第三方协作。

## Day 4：三条端到端路径和失败状态

| 任务目标 | 工时分配 | 前置条件 | 可验收结果 |
| --- | --- | --- | --- |
| 把 claimant UI 的动态表单、Agent 动作和 Claim Context 接通 | `Ysoseri1224 3h` | Day 2–3 功能 | motor、home、contents 均可运行客户侧主流程 |
| 接通第三方状态、隐私提示和人工交接展示 | `Ysoseri1224 2h` | handoff/service 状态 | 客户能看到共享范围、等待原因、失败状态和下一步 |
| 复现 claimant、Agent 和动态表单整合 | `Ysoseri1224 1h` | 同日整合结果 | 一次 review 覆盖三个相关功能，记录影响用户推进的问题 |
| 将 Agent 状态结果映射到 claimant UI 和 Agent 动作展示 | `Ysoseri1224 2h` | 统一状态模型、Agent action contract | claimant 页面按 Agent 已决定的状态显示动态表单、下一步和用户可执行操作 |
| 将已批准状态/action contract 映射到 API、持久化和事件字段 | `jxu316-arch 2h` | 统一状态模型、后端 action contract | 同一转换在后端和数据层使用一致状态值；不重新判断 Agent 行为 |
| 实现 API、RAG、provider adapter 和 Control Plane 的整合 | `liyang6620 3h` | Day 2–3 API | 三条线使用同一 API 契约，真实可用 provider 被调用 |
| 检查 AWS/云端能力和互斥运行配置边界 | `liyang6620 2h` | 实际访问结果 | 未确认的 AWS 能力标为 unavailable/pending，不写成已完成 |
| 将数据来源、连接状态和错误结果投影到统一 API 响应 | `liyang6620 2h` | API/adapter 整合结果 | 前端可以区分有来源结果、无结果、超时和不可用状态 |
| 复现数据、配置和 API 整合 | `liyang6620 1h` | 同日整合结果 | 一次 review 覆盖 RAG、adapter 和 Control Plane |
| 打通 Claim Context、resume、evidence、handoff 和事件记录 | `jxu316-arch 3h` | Day 2–3 persistence | 客户恢复、staff 接手和第三方更新使用同一份状态 |
| 检查 revision 冲突、重复请求和并发更新 | `jxu316-arch 2h` | event/revision model | 较新的状态不会被旧操作覆盖，重复请求有明确结果 |
| 复现后端整合和多端状态一致性 | `jxu316-arch 1h` | 同日整合结果 | 一次 review 覆盖 context、resume、handoff 和 revision |
| 打通 staff queue、详情、Agent 协作和 claimant 状态更新 | `LLL263 3h` | Day 3 Workbench | staff 能从队列进入详情、执行操作并看到结果 |
| 打通 staff 侧第三方状态和操作入口 | `LLL263 2h` | third-party API | staff 能处理授权、等待、完成、失败和待补信息 |
| 让 staff action 结果同步到 claimant 状态卡片 | `LLL263 1h` | customer projection、write-back API | staff 完成操作后，客户侧能看到不泄漏内部信息的状态更新 |
| 复现 staff 整合和 customer projection | `LLL263 2h` | 同日整合结果 | 一次 review 覆盖 Workbench、第三方状态和客户可见更新 |
| 实现 evidence、第三方请求、结果和失败状态的端到端连接 | `bdfa123 3h` | Day 3 service | 三条线使用相同 evidence/source/status 规则 |
| 隔离正常运行入口与测试 fixture 入口 | `bdfa123 2h` | runtime config | 正常运行不会读取 fixture 成功值，测试仍可独立加载 fixture |
| 保留失败上下文并向前端提供可继续处理的状态 | `bdfa123 2h` | error projection、Claim Context | 服务失败后 claim 不丢失，客户和 staff 能看到下一步或人工处理要求 |
| 复现 evidence、服务错误和入口隔离 | `bdfa123 1h` | 同日整合结果 | 一次 review 覆盖三个相关功能，保留复现记录 |

**Day 4 容量：** 每人 8 小时，全组 40 小时。三条代表性路径均可完成一次客户侧和 staff 侧运行，并能观察成功、失败、等待、拒绝和未知结果。

## Day 5：重复验证、修复和 Week 6 输入

| 任务目标 | 工时分配 | 前置条件 | 可验收结果 |
| --- | --- | --- | --- |
| 共同完成一轮三条路径的 claimant-to-staff 演练 | `Ysoseri1224 2h + LLL263 2h` | Day 4 端到端路径 | 两人分别负责 claimant 操作/Agent行为和 staff 接手/Workbench 操作，完整记录中断点和结果 |
| 修复 Agent 行为边界和提示词问题 | `Ysoseri1224 3h` | 演练记录 | 快速、复杂、紧急、人工和待补材料场景符合状态和权限边界 |
| 修复 claimant 动态表单、隐私和状态展示问题 | `Ysoseri1224 2h` | 演练记录 | 没有未注册字段；客户能理解确认、共享和下一步 |
| 复现修复后的 Agent、表单和隐私功能 | `Ysoseri1224 1h` | 修复结果 | 一次 review 覆盖三个相关功能并记录结果 |
| 验证 RAG 来源、provider 切换和 Control Plane 配置 | `liyang6620 3h` | Day 4 整合结果 | 每项结果有来源；切换后不混用旧连接或旧数据 |
| 修复数据/API/adapter 的错误状态和边界 | `liyang6620 2h` | 验证记录 | no-result、timeout、unavailable 和错误响应符合约定 |
| 整理 AWS/云端可用能力和 Week 6 连接输入 | `liyang6620 2h` | 实际运行记录 | 清单区分已验证、部分可用、待确认和不可用能力 |
| 复现数据、adapter 和 Control Plane 修复 | `liyang6620 1h` | 修复结果 | 一次 review 覆盖三个相关功能 |
| 修复 Claim Context、revision、resume 和 handoff 一致性问题 | `jxu316-arch 3h` | Day 4 运行记录 | 恢复和接手后状态一致，重复写入可识别 |
| 修复第三方 stakeholder 和状态机后端映射问题 | `jxu316-arch 2h` | 状态机复现记录 | stakeholder、允许动作和失败状态清楚且可追溯 |
| 检查三条线的状态和事件链路 | `jxu316-arch 2h` | 修复结果 | 同一状态模型适用于三条线，不复制互相冲突的状态 |
| 复现 context、handoff 和状态机修复 | `jxu316-arch 1h` | 修复结果 | 一次 review 覆盖三个相关后端功能 |
| 修复 staff Workbench、接手和第三方操作问题 | `LLL263 3h` | Day 5 演练记录 | staff 能直接理解上下文并完成操作，不需重复收集信息 |
| 修复 staff/customer 信息投影和 Agent 协作问题 | `LLL263 1h` | visibility 复现结果 | internal signal 不泄漏，客户获得适当状态更新 |
| 补齐 staff 页面在空数据、加载中和错误状态下的操作反馈 | `LLL263 1h` | Workbench 运行记录 | staff 在每种状态下都能知道当前情况和可执行动作 |
| 复现 Workbench、第三方状态和 customer projection | `LLL263 1h` | 修复结果 | 一次 review 覆盖三个相关界面功能 |
| 修复 evidence、第三方失败、结果验证和重试问题 | `bdfa123 3h` | Day 4 运行记录 | 请求重复、来源丢失、结果未验证和上下文丢失问题得到处理 |
| 整理三条线的测试场景、fixture 和运行限制 | `bdfa123 2h` | 全周运行记录 | fixture 仅用于测试；每个限制有复现步骤和当前状态 |
| 补齐三条线的失败状态回归检查 | `bdfa123 2h` | 测试场景清单 | 每条线都覆盖 timeout、unavailable、拒绝和未知结果 |
| 复现 evidence、第三方服务和失败处理修复 | `bdfa123 1h` | 修复结果 | 一次 review 覆盖三个相关功能 |

**Day 5 容量：** 每人 8 小时，全组 40 小时。得到可重复运行的 VP Week 5 基线、问题清单和 Week 6 输入。

## 每日容量核对

| 成员 | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | 正常合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Ysoseri1224` | 8h | 8h | 8h | 8h | 8h | 40h |
| `liyang6620` | 8h | 8h | 8h | 8h | 8h | 40h |
| `jxu316-arch` | 8h | 8h | 8h | 8h | 8h | 40h |
| `LLL263` | 8h | 8h | 8h | 8h | 8h | 40h |
| `bdfa123` | 8h | 8h | 8h | 8h | 8h | 40h |
| **全组** | **40h** | **40h** | **40h** | **40h** | **40h** | **200h** |

## 额外任务（不计入每日 8 小时）

| Issue | 负责人 | 工时 | 说明 |
| --- | --- | ---: | --- |
| `#363` | `Ysoseri1224` | 8h | 额外任务；若建卡，拆成两张各 4h 的关联卡，合计仍记录为 8h |
| `#364` | `Ysoseri1224` | 1h | 额外任务单独建卡，不计入当天正常 8h |

## 建卡前检查

- 每张 card 都有页面、API、数据记录、状态变化、可调用接口或复现记录作为验收依据。
- Day 1 的定义任务都直接服务于当天实现；没有成员整天只做定义。
- 多人 card 写明每个人的实际分工和个人工时。
- Review card 独立统计，通常为 1–2 小时，并可覆盖多个相关功能。
- 三条 VP 线每天都有功能推进，不把它们写成产品范围限制。
- 运行时真实服务与测试 fixture 入口分开；不可用能力明确显示错误。
- 正常任务每天每人 8 小时；#363/#364 作为额外工时单独统计。
