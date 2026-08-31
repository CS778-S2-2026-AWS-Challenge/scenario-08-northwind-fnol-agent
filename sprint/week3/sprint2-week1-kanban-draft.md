# Sprint 2 第一周 Kanban 任务草案

## 文档用途

这是供内部确认的中文草案，尚未创建到 GitHub Kanban。

- **周期：** 2026 年 8 月 17 日至 21 日
- **容量：** 5 人 × 5 天 × 8 小时 = 200 人时
- **任务数量：** 每天 10 张，共 50 张拟议 card
- **单张工时：** 每张 4 人时
- **任务语言：** 本草案用中文；确认后上传 Kanban 的版本用英文
- **序号：** 只用于草案定位，不写入实际 card title

## Sprint 2 主张

用两周把 Sprint 1 的全路径 prototype 推进为可重复运行的 MVP：团队按栈
负责，并围绕五条业务路径并行开发；可用的 AWS 能力从第一周起持续接入，
最终汇合为从报案到 claim 创建或人工接管的端到端路径。

## 栈级分工

| 成员 | 主要责任栈 |
| --- | --- |
| `Ysoseri1224` | Claimant frontend + Agent behaviour |
| `liyang6620` | Backend API + AWS integration |
| `jxu316-arch` | Persistence/session + policy/history data |
| `LLL263` | Staff workbench + handoff/write-back workflow |
| `bdfa123` | Evidence/media lifecycle + fixture infrastructure |

任务按业务路径组织，人员仍按上述技术栈负责。测试由实现者完成基础检查，再由
其他成员独立验收；`bdfa123` 不单独负责最终质量门。

## Day 1：建立五条路径的栈级基线

Day 1 不先完成一份庞大设计。每个栈直接在相关路径中确认输入输出，并建立可
独立运行的 contract、adapter 或 fixture 基线。

| 序号 | 路径 | 拟议任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | Clear claim | 建立 claimant 与 Agent 的清晰报案基线 | `Ysoseri1224 4h` | 现有 SPEC 和 API contract | describe、confirm、correct、proceed 的 customer/Agent fixture | 无需 backend 即可重复展示输入、确认和下一步状态变化 |
| 2 | Clear claim | 建立 claim creation API 与 AWS 边界 | `liyang6620 4h` | 现有 API contract | create/route 接口、AWS service boundary 和 fallback 约定 | fixture 请求返回 claim 状态、route、next step 和来源标记 |
| 3 | Pending evidence and resume | 建立 session、resume 与 revision 模型 | `jxu316-arch 4h` | 现有 persistence schema | session snapshot、unresolved work、revision 和恢复规则 | 同一 fixture claim 可跨 session 恢复，旧 revision 不覆盖新状态 |
| 4 | Pending evidence and resume | 建立 evidence 生命周期与 fixture | `bdfa123 4h` | 现有 Claim State | pending、unofficial、incomplete、not-yet-generated 和 received evidence fixture | 每种材料状态均有 source、visibility、next requirement 和预期状态变化 |
| 5 | Human request and urgent handoff | 建立人工请求和紧急 Agent 行为 | `Ysoseri1224 4h` | Agent behaviour SPEC | human request、repeat request、injury 和 continuing danger action fixture | 每种输入产生明确 action、reason、priority 和 customer next step |
| 6 | Human request and urgent handoff | 建立 staff handoff 队列基线 | `LLL263 4h` | 现有 handoff contract | urgent、human request 和 professional review 队列与 handoff card | staff 能看到 priority、confirmed facts、gaps、reason 和 requested action |
| 7 | Policy/history and professional review | 核对 AWS policy/history 可用性与 API 边界 | `liyang6620 4h` | 当前 AWS 权限 | access、service、schema、permission、API boundary 和 fallback 记录 | 每项能力明确标记可用、不可用或待确认，不把未知项写成事实 |
| 8 | Policy/history and professional review | 建立 policy/history persistence 与 mapping 基线 | `jxu316-arch 4h` | 现有 domain model | provider-to-domain mapping、source、retrieved_at 和 uncertainty 字段 | 示例数据可映射到 domain record，不向公共 API 泄漏 provider payload |
| 9 | Staff action and write-back | 建立 staff action 与状态回写基线 | `LLL263 4h` | 现有 staff action contract | assign、review、resolve、write-back 和 customer update fixture | action 包含 actor、reason、result；customer update 不包含 internal signal |
| 10 | Staff action and write-back | 建立 evidence 可见性与场景 fixture 基线 | `bdfa123 4h` | 现有 visibility rules | customer/shared/internal evidence fixture 和五条路径的场景入口 | internal evidence 不出现在 customer fixture；场景无需手改数据即可加载 |

### Day 1 工时核对

每人两张 4h card，共 8h；全组 40h。

## Day 2：推进 Clear Claim 与 Pending Evidence/Resume

| 序号 | 路径 | 拟议任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | Clear claim | 实现 claimant 对话、表单和确认路径 | `Ysoseri1224 4h` | Clear claim claimant/Agent 基线 | conversation、visible form、confirmation 和 correction UI | 页面由 Claim State 驱动；修改 proposed fact 后显示新值和来源 |
| 2 | Clear claim | 实现 claim creation 与 routing API | `liyang6620 4h` | claim creation API 边界 | fixture-backed create/route API、错误和 retry 结果 | 重试不会重复创建 claim；响应包含 route、next step 和 known timing |
| 3 | Clear claim | 实现 claim 与 session repository | `jxu316-arch 4h` | session/revision 模型 | claim/session save、read、update 和 revision check | claim 可保存并在新 session 读取；revision conflict 返回明确错误 |
| 4 | Clear claim | 实现 evidence 上传与 mock storage | `bdfa123 4h` | evidence 生命周期基线 | 图片/PDF metadata、mock storage reference、processing state 和 source | 上传后可读取 metadata；文件内容和 storage key 不暴露给公共 payload |
| 5 | Clear claim | 实现 created/routed staff 视图 | `LLL263 4h` | staff queue 基线 | created/routed queue、claim summary 和 next staff action | staff 能识别 route、evidence state 和后续责任，不需要读取完整对话 |
| 6 | Pending evidence and resume | 实现 Agent 的 pending/resume 行为 | `Ysoseri1224 4h` | evidence fixture；session model | missing-later evidence、resume summary 和 focused next question | 未来材料不阻塞无关步骤；返回后不重复已确认问题 |
| 7 | Pending evidence and resume | 实现 evidence/session API 与 AWS storage boundary | `liyang6620 4h` | evidence lifecycle；AWS boundary | evidence state、upload metadata、resume 和 storage adapter API | 未接入 AWS 时 fixture 路径可运行；接入状态和 fallback 清楚可查 |
| 8 | Pending evidence and resume | 实现跨 session 恢复与 unresolved work | `jxu316-arch 4h` | claim/session repository | session summary、pending evidence、prior commitment 和 resume query | 十天后返回的 fixture session 能恢复同一 claim 和未完成事项 |
| 9 | Pending evidence and resume | 实现 staff pending-evidence 视图 | `LLL263 4h` | staff queue 基线 | evidence pending queue、responsible party、expected timing 和 context | staff 能区分等待 claimant、外部机构或内部处理，不错误关闭 claim |
| 10 | Pending evidence and resume | 实现 evidence 状态转换和 proposed facts | `bdfa123 4h` | upload/mock storage | processing、proposed、confirmed、rejected 和 pending 状态转换 | 图片提取事实确认前保持 proposed；状态转换保留 source 和时间 |

### Day 2 工时核对

每人两张 4h card，共 8h；全组 40h。

## Day 3：推进 Handoff、Professional Review 与 Write-Back

| 序号 | 路径 | 拟议任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | Human request and urgent handoff | 实现 claimant 人工请求与紧急中断体验 | `Ysoseri1224 4h` | Agent handoff fixture | first request、repeat request、urgent interruption 和 transfer UI | Agent 不重复阻止人工请求；urgent signal 中断普通提问并显示明确下一步 |
| 2 | Policy/history and professional review | 实现 policy ambiguity 与 review Agent 行为 | `Ysoseri1224 4h` | policy/history mapping 基线 | evidence-grounded clarification、review reason 和 authority boundary | Agent 显示依据和不确定性，不自行作 coverage/fraud 结论 |
| 3 | Human request and urgent handoff | 实现 handoff API 与 AWS/service fallback | `liyang6620 4h` | handoff contract；AWS boundary | create/read/accept handoff、priority、error 和 fallback API | handoff 保存结构化 context；外部服务失败时仍能保留请求和状态 |
| 4 | Policy/history and professional review | 实现 policy/history retrieval API | `liyang6620 4h` | AWS 可用性记录 | retrieval adapter、source projection、unavailable 和 timeout 响应 | 可用数据被返回并标明来源；不可用时不生成虚假结论 |
| 5 | Human request and urgent handoff | 实现 handoff persistence 与 ownership | `jxu316-arch 4h` | persistence 基线；handoff API shape | handoff record、priority、owner、status、reason 和 revision | handoff 可被 staff 接受并写回；重复请求不生成冲突 ownership |
| 6 | Policy/history and professional review | 实现 policy/history record 与 review signal mapping | `jxu316-arch 4h` | policy/history mapping | retrieval record、source evidence、uncertainty 和 supported review signal | review signal 有来源和理由，不自动阻塞 claim 或变成欺诈认定 |
| 7 | Human request and urgent handoff | 实现 urgent 与 human-request staff 队列 | `LLL263 4h` | staff queue；handoff API shape | priority queue、ownership、handoff summary 和 accept action | staff 能按 priority 接管，并看到已确认事实、缺口和 requested action |
| 8 | Policy/history and professional review | 实现 professional-review 详情与处理界面 | `LLL263 4h` | staff detail；review signal mapping | policy source、uncertainty、signal、confirm/dismiss/resolve actions | staff 可记录理由和结果；customer 只收到适当状态更新 |
| 9 | Human request and urgent handoff | 组装 evidence handoff packet | `bdfa123 4h` | evidence lifecycle；handoff contract | evidence list、source、state、gaps 和 visibility projection fixture | handoff packet 包含 staff 所需材料上下文，internal evidence 不泄漏给 customer |
| 10 | Policy/history and professional review | 建立 professional-review 场景 fixture | `bdfa123 4h` | policy/history mapping；evidence fixtures | coverage ambiguity、history signal、conflicting evidence 和 unavailable data 场景 | 每个场景有预期 action、evidence state、review reason 和 visibility 结果 |

### Day 3 工时核对

每人两张 4h card，共 8h；全组 40h。

## Day 4：完成各栈内路径连接和失败状态

Day 4 继续在各栈内部连接五条路径，不把 Week 4 才能完成的跨栈汇合提前标记
为 Done。

| 序号 | 路径 | 拟议任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | Clear claim + Pending evidence | 连接 claimant UI 与 Agent controller | `Ysoseri1224 4h` | Day 2 claimant/Agent 实现 | describe、confirm、pending、resume 的 claimant-to-Agent 本地路径 | 页面状态来自统一 Claim State fixture，不使用静态跳页或隐藏状态 |
| 2 | Handoff + Professional review | 连接 claimant handoff 与 Agent authority boundary | `Ysoseri1224 4h` | Day 3 Agent 实现 | human、urgent、policy ambiguity 和 review 的本地路径 | 每条路径显示正确 reason、priority、authority result 和 next step |
| 3 | Clear claim + Pending evidence | 连接 API、claim creation 与可用 AWS adapter | `liyang6620 4h` | Day 2 API；AWS boundary | API-to-adapter 本地路径和来源标记 | 已确认 AWS 能力直接调用；未确认部分使用同契约 fixture 并明确标记 |
| 4 | Handoff + Professional review | 连接 handoff、retrieval 与 fallback API | `liyang6620 4h` | Day 3 API | handoff/retrieval 成功、timeout、unavailable 和 retry 行为 | 外部失败不会丢失 claim/handoff；错误响应符合 API contract |
| 5 | Clear claim + Resume + Handoff | 连接 repository、session 与 handoff records | `jxu316-arch 4h` | Day 2-3 persistence | 同一 Claim State 下的 claim/session/handoff 持久化路径 | resume 和 handoff 使用同一 revision；不存在互相覆盖的私有状态 |
| 6 | Policy/history + Staff write-back | 连接 retrieval records、review signals 与 revision | `jxu316-arch 4h` | Day 3 mapping | source evidence、signal、staff result 和 write-back persistence | staff result 保留 actor/reason；source evidence 可追溯且不被覆盖 |
| 7 | Handoff + Professional review | 连接 staff queue、detail 与 accept/review actions | `LLL263 4h` | Day 3 staff UI | queue-to-detail-to-action 本地 staff 路径 | staff 可接管、review 和 resolve；页面同步显示 ownership 与状态 |
| 8 | Staff action and write-back | 连接 staff action 与 claimant update projection | `LLL263 4h` | staff action fixture | staff write-back、customer update、empty/loading/error states | customer update 不包含 internal signal；失败时不丢失 staff 输入 |
| 9 | Evidence across all paths | 连接 evidence lifecycle、mock storage 与路径 fixture | `bdfa123 4h` | Day 2-3 evidence 实现 | clear、pending、handoff 和 review 使用的统一 evidence fixture service | 所有路径使用相同 evidence state 和 source 规则，不复制私有材料模型 |
| 10 | Evidence across all paths | 检查 evidence/visibility 并记录路径缺陷 | `bdfa123 4h` | evidence fixture service | evidence 状态差异、visibility 结果和复现记录 | 发现的问题分配给所属栈；`bdfa123` 不独自修复其他栈缺陷或决定通过 |

### Day 4 工时核对

每人两张 4h card，共 8h；全组 40h。

## Day 5：跨成员验收并准备 Week 4 汇合

Day 5 由非实现者参与验收。每张 card 仍由栈负责人修复和说明，但通过结果不能
只由实现者本人确认。

| 序号 | 路径 | 拟议任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | Clear claim | 验收 claimant 与 Agent 清晰报案路径 | `Ysoseri1224 3h` 修复/演示；`bdfa123 1h` evidence 独立检查 | Clear claim claimant/Agent 输出 | describe、confirm、correct、proceed 演示和问题记录 | 给定 fixture 可重复完成；事实来源、确认状态和下一步正确 |
| 2 | Clear claim | 验收 API、claim creation 与 persistence | `liyang6620 3h` API/AWS；`jxu316-arch 1h` persistence 检查 | Clear claim backend/data 输出 | create/route、repository、retry 和 source 演示 | 不重复创建 claim；route、revision、source 和 fallback 可追溯 |
| 3 | Pending evidence and resume | 验收 claimant/Agent pending 与恢复路径 | `Ysoseri1224 3h` 修复/演示；`LLL263 1h` staff status 检查 | Pending/resume UI 与 Agent 输出 | pending evidence、resume 和 next step 演示 | 材料未生成不阻塞无关步骤；返回后不重复已确认事实 |
| 4 | Pending evidence and resume | 验收 session persistence 与 evidence lifecycle | `jxu316-arch 3h` persistence；`bdfa123 1h` evidence 检查 | Pending/resume data 输出 | session restore、evidence state、source 和 revision 演示 | 同一 claim 可恢复；evidence 状态和 visibility 在保存后不丢失 |
| 5 | Human request and urgent handoff | 验收 staff handoff 体验 | `LLL263 3h` staff workflow；`Ysoseri1224 1h` claimant update 检查 | Handoff UI 输出 | queue、handoff context、accept action 和 customer update 演示 | staff 不需重读聊天即可接管；customer 获得适当状态更新 |
| 6 | Human request and urgent handoff | 验收 handoff API、priority 与 fallback | `liyang6620 3h` API/AWS；`bdfa123 1h` packet evidence 检查 | Handoff API/data 输出 | handoff create/read/accept、priority、retry 和 failure 演示 | 紧急路径不被普通 intake 阻塞；外部失败时请求和 context 不丢失 |
| 7 | Policy/history and professional review | 验收 data adapter、mapping 与 review record | `jxu316-arch 3h` data/persistence；`liyang6620 1h` AWS/API 检查 | Professional-review data 输出 | source、uncertainty、review signal 和 unavailable fallback 演示 | 不产生无来源 policy/fraud 结论；adapter 与 domain contract 一致 |
| 8 | Policy/history and professional review | 验收 authority boundary、evidence 与 staff review | `bdfa123 2h` evidence fixture；`Ysoseri1224 1h` Agent boundary；`LLL263 1h` staff review | Professional-review 各栈输出 | ambiguity/conflict 场景和三方 visibility 结果 | Agent 不越权，staff 能处理，customer 看不到 internal signal |
| 9 | Staff action and write-back | 验收 staff action、write-back 与 Claim State | `LLL263 3h` staff workflow；`jxu316-arch 1h` revision 检查 | Staff write-back 输出 | assign/review/resolve、actor/reason/result 和 customer projection 演示 | write-back 使用当前 revision；customer/internal projection 正确分离 |
| 10 | 五条路径 | 汇总栈级兼容性和 Week 4 输入 | `bdfa123 3h` evidence/fixture 清单；`liyang6620 1h` API/AWS 输入确认 | 前九项验收 | endpoint、state、adapter、fixture、blocker、owner 和 fallback 清单 | 每个 Week 4 集成点都有提供方、使用方和当前状态；未完成项不标 Ready |

### Day 5 工时核对

| 成员 | 分配 | 合计 |
| --- | --- | ---: |
| `Ysoseri1224` | Clear 3h + Pending/resume 3h + Handoff claimant 检查 1h + Agent boundary 1h | 8h |
| `liyang6620` | Clear API 3h + Handoff API 3h + AWS/API 检查 1h + Week 4 输入 1h | 8h |
| `jxu316-arch` | Clear persistence 1h + Pending/resume 3h + review data 3h + write-back revision 1h | 8h |
| `LLL263` | Pending staff 检查 1h + handoff staff 3h + review staff 1h + write-back 3h | 8h |
| `bdfa123` | Clear evidence 1h + pending evidence 1h + handoff evidence 1h + review evidence 2h + Week 4 fixture 3h | 8h |
| **总计** | | **40h** |

## 全周工时核对

| 成员 | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | 周合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Ysoseri1224` | 8h | 8h | 8h | 8h | 8h | 40h |
| `liyang6620` | 8h | 8h | 8h | 8h | 8h | 40h |
| `jxu316-arch` | 8h | 8h | 8h | 8h | 8h | 40h |
| `LLL263` | 8h | 8h | 8h | 8h | 8h | 40h |
| `bdfa123` | 8h | 8h | 8h | 8h | 8h | 40h |
| **总计** | **40h** | **40h** | **40h** | **40h** | **40h** | **200h** |

## 创建 Kanban 前需要确认

1. 五个栈级责任包是否准确、工作量是否相对均衡。
2. 五条纵向路径是否覆盖 MVP 的核心目标。
3. AWS 是否从 Day 1 起持续推进，而不是推迟到 Week 4。
4. `bdfa123` 的 Evidence/media 栈是否足够明确且具备产品价值。
5. 测试是否由全员负责并包含非实现者验收。
6. 每张 card 的 4 小时是否与交付物和验收范围相符。

确认后，再把接受的任务翻译成英文并创建到 Kanban board。
