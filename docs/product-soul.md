# Northwind 自适应 FNOL 产品定义

## 1. 文档地位

本文是 Northwind FNOL 项目的产品权威文档，回答“为什么做、为谁做、产品必须怎样工作、什么不能被牺牲”。详细 Sprint、技术设计、任务分配和测试计划必须与本文一致。

资料优先级：

1. 原题事实、数字和最终验收要求以 Scenario 8 brief 为准；当前 Sprint 和仓库验收文件必须明确记录其可验证范围与限制。
2. 当前产品主张、产品需求和边界以本文为准。
3. Sprint 1 的实现与验收以 [`../sprint/week2/sprint1.md`](../sprint/week2/sprint1.md) 为准。
4. 竞标方案、工作流和决策理由仅作为背景参考；如果没有随仓库交付的证据，不得把它们当成当前工程合同或生产能力证明。

任何文档都必须区分：Brief 事实、用户确认的产品决策、团队判断、待验证假设和未来目标。

## 2. 产品主张

> **建立一个可信的理赔协同入口，让客户自然讲述发生的事情，由系统承担背后的专业整理和流程推进，并持续负责把理赔带到下一安全步骤。**

这个总体目标在当前 FNOL 范围内落实为：一个自适应 Agent 根据 claim 与用户状态
分配客户努力、系统工作和人工判断，使案件安全推进到下一步并最终创建完整、可继续
处理的 claim record。这里的“可信”不是模型看起来专业，而是每个重要事实、来源、
权限、状态变化和人工决定都能被核实。

这里的“完整”是指 claim 创建所需的结构化事实、来源、证据状态、待办、路由和责任均已被可靠记录；它不等于在 FNOL 阶段收齐整个 claim 生命周期的所有未来材料。

产品不是聊天版 Web Form，也不是 Contact Centre 或 Claims Professional 的替代品。它把现有两种渠道的互补能力组织为一条连续服务：

- 保留数字渠道的即时性、结构化和可扩展性；
- 提供接近人工服务的自然语言理解、澄清和例外处理；
- 在需要支持或专业判断时携带上下文转交人工；
- 不要求客户先理解保险流程、内部组织或所需字段。

## 3. 问题与价值

Northwind 当前主要依赖 Contact Centre 和 Web Form：

- Contact Centre 能理解自然语言和例外，但消耗大量员工时间，复杂 policy 问题仍可能处理困难；
- Web Form 较快且结构化，但冗长、僵硬，无法根据事故和用户情况改变提问，也不能及时澄清；
- 两者都缺少系统性的图片和文件采集；
- Brief 明确 40% 的 FNOL 需要至少一次 follow-up，首次报案到 claim 创建平均为 2.5 天（包括缺失信息的 follow-up）；它没有证明材料具体在何时被发现；
- 产品必须避免客户等到后续人工处理时才首次得知材料问题，并持续说明当前状态和补充方式；
- FNOL 缺少根据案件复杂度、决策影响、证据状态和用户支持需求动态分配 effort 的机制。

Agent 的价值不是“使用 AI”，而是：

1. Claimant 用自然语言一次描述，Agent 维护专业、结构化的 claim form。
2. 只问当前安全动作真正需要的问题，减少无关提问和重复说明。
3. 对简单案件减少人工介入，对复杂和高影响案件更早提供完整的专业判断上下文。
4. 即使材料尚未生成或暂时缺失，也持续说明状态并推进仍可安全进行的步骤。
5. 即使相隔 8-10 天再继续会话，也能恢复案件状态，而不是要求用户重新开始。

## 4. 用户

### Claimant

事故、盗窃或灾害后需要立即开始 claim，但不了解保险流程、证据要求和下一步的 reporting customer。

Claimant 需要：

- 用自己的语言描述事件；
- 查看并纠正 Agent 的专业化理解；
- 知道当前状态、还缺什么、为什么需要以及何时再提供；
- 在紧急、困难、不耐烦、无障碍或个人偏好情况下获得合适支持；
- 转交人工后不重复已经提供的内容。

### Staff 作为 Agent 的另一类核心用户

Agent 的受众不只有 claimant。Claims Professional 和相关 staff 也需要在日常工作中
使用 Agent，并且应从中获得更好的工作体验和更低的处理成本。Agent 应帮助 staff：

- 更快理解一份 claim 的已确认事实、来源、缺口和冲突；
- 在不重读完整聊天记录的情况下继续处理；
- 追问、修正、拒绝或覆盖 Agent 的建议，并清楚看到决定对 claim state 的影响；
- 以自然语言获取 Agent 的分析和建议，而不是被限制在一组预定义按钮内；
- 对 Agent 的依据、局限和不确定性保持足够信任和使用意愿。

Agent 不替 staff 做最终的高影响决定。它的目标是减少重复信息收集和上下文重建，
让 staff 把时间用于专业判断、客户支持和例外处理。

### Claims Professional 与相关专业团队

人工接手者需要直接获得：

- 经客户确认的事故摘要和结构化 form；
- 每个关键字段的来源和状态；
- 已有图片、PDF 和其他证据；
- 缺失、冲突、待生成或低置信度信息；
- 转交原因、风险和需要人工完成的决定；
- 已发生的客户沟通和已承诺的下一步。

人工应把时间用于专业判断、支持和例外，不应用于重新收集已有信息。

企业端用户通过系统维护的 Claim Operations Workbench 查看和处理 claim。Workbench 是 claim state 的实时投影，不是员工另行手工维护的第二套看板。

### Northwind Claims Operations

流程负责人需要减少可避免补件和人工受理时间，更快创建和路由 claim，并在业务量增长时避免人工规模同比增长，同时维持治理、审计和客户信任。

## 5. 为什么用户会选择 Agent

Agent 必须提供相对 Web Form 和电话可感知的优势：

- 相比固定表单：允许自然语言、动态澄清、图片理解、按需提问、跨会话继续和实时进度；
- 相比电话：无需排队、随时继续、信息与材料可见、结构化状态持续保存；
- 相比二者：在自动化与人工之间切换时保留上下文，避免重复和流程重启。

接纳率来自专业、准确、透明和可控的服务行为，不来自宣传模型能力。Agent 必须允许纠正、不假装确定性、不隐瞒人工路径，也不能通过无止境提问把客户困在自动化中。

### 为什么不是直接使用通用 GPT

通用模型可以生成看起来合理的保险解释，但不能单独保证一件真实理赔工作的连续、
可追踪和可执行。Northwind 的差异不以“训练了更专业的模型”为前提，而以以下可
验证能力为准：

- 根据授权的客户保单和来源回答，而不是只依据一般常识；
- 区分客户原话、Agent 推断、材料证据和工作人员判断；
- 跨会话保持 claim 状态和未完成事项；
- 判断当前信息是否足以执行下一安全动作；
- 在紧急、模糊或高影响情况下停止自动处理并正确转交；
- 调用企业系统创建 claim、安排处理并持续更新；
- 让每一步都有来源、权限边界和审计记录。

模型、RAG、规则、数据库、工具调用和人工审核都是这项能力的组成部分。本项目不以
训练或微调模型为目标，而是通过 Agent 行为设计、提示词调优、结构化输出约束和运行时
边界提高可靠性。评估至少要比较：来源是否正确、关键事实是否遗漏、高风险动作是否
被错误执行、隔几天回来后是否保持一致、人工接手后是否能直接继续，以及客户和 staff
各自需要回答、阅读和重复多少内容。

## 6. 核心运行模型

```text
客户描述事件并提供材料
        ↓
Agent 识别 policy、incident 和当前用户需要
        ↓
Agent 更新结构化 form，并标记来源、状态和不确定性
        ↓
客户查看、确认或纠正关键理解
        ↓
Agent 查询 policy、历史 claim 和当前证据
        ↓
判断当前 next safe action
        ↓
询问 / 澄清 / 推进 / 创建 / 更新 / 转交 / 紧急升级
        ↓
客户与接手人员获得与各自任务相符的下一步
```

Agent 的最小动作集合为：

- `ASK`：询问当前动作真正需要的信息；
- `CLARIFY`：处理歧义、冲突、缺漏或材料质量问题；
- `CONFIRM`：让用户确认或纠正关键事实；
- `PROCEED`：执行已满足条件的下一安全动作；
- `UPDATE`：说明状态、等待事项、责任方和时间；
- `HANDOFF`：携带上下文转交人工支持或专业判断；
- `URGENT_HANDOFF`：在伤亡、持续危险或其他明确紧急信号下中断普通流程并升级；
- `CREATE_CLAIM`：向 mock 或正式 claims system 创建并路由 claim。

## 7. 自适应能力

Agent 必须同时考虑：

1. **Claim 状态**：incident nature、已知事实、缺失信息、信息冲突、证据状态、coverage、severity、fraud signal 和下一动作影响。
2. **用户状态**：理解程度、耐心、情绪、无障碍需求、是否能够或愿意继续自助，以及是否明确请求人工。
3. **系统状态**：policy、历史 claim、外部文件、claims system 和 assessor 服务是否可用。
4. **成本状态**：继续对话的 token/延迟成本与人工接入后的执行和认知成本。

Claim 不应被压缩成一条互斥“路径”。系统应维护可组合的多维状态属性，再由规则和 Agent 选择下一动作。核心属性至少包括：

```text
severity: fast_track | standard | complex
coverage: clear | ambiguous | review_required
evidence: received | unofficial | incomplete | pending_generation | inconsistent
fraud_signal: none | review_required
customer_support: self_service | guided | human_requested | accessibility_required
urgency: normal | urgent | immediate_safety_risk
workflow_state: collecting | ready_for_next | awaiting_evidence | professional_review | created
next_action
```

同一 claim 可以同时为 `severity: standard`、`coverage: clear`、`evidence: police_report_pending`、`fraud_signal: none`、`customer_support: guided`、`next_action: create_claim`。单一待补材料不得覆盖其他维度并错误阻塞整个流程。

至少覆盖以下路径：

- **快速路径**：信息明确、风险较低且用户可继续自助，减少问题并直接推进；
- **引导路径**：通过针对性澄清、form 更新和客户确认解决可处理的歧义；
- **专业判断路径**：coverage、事件性质、证据冲突或高影响决定无法安全自动处理时主动转交；
- **紧急路径**：明确人员伤亡、持续危险或紧急援助需要时立即给出安全提示并高优先级升级；
- **用户请求人工路径**：识别请求原因并提供清晰选择；不得反复阻止转交，重复请求、支持需要或紧急情况应立即升级；
- **待补材料路径**：材料尚未生成、缺失、不完整或冗余时，不默认阻塞全部流程；记录状态并推进不依赖该材料的安全动作；
- **跨会话路径**：恢复未完成 claim、未解决问题和已承诺下一步；
- **Fraud review 路径**：基于历史 claim 和当前不一致产生有依据的 signal，交由专业人员复核，不自动认定欺诈。

## 8. 对话式 Form

结构化 form 是 claim 的持续状态，不是对话结束后的附属摘要。

Agent 必须：

- 从自然语言和材料中提出字段值；
- 把客户语言转换为专业、清晰但不改变事实的表达；
- 为字段保留原始来源、置信度和确认状态；
- 在用户请求时以及关键确认、创建和转交节点显式展示 form，并允许用户确认和纠正；
- 避免再次询问已经确认的信息；
- 在人工接手时直接提供当前 form。

字段至少具有：

```text
value
source: claimant | image | document | policy | claim_history | inference
status: proposed | confirmed | disputed | missing | pending_generation
needed_for: current_action | later_action
updated_at
```

## 9. Next-action-ready 与材料管理

> **当现有信息足以支持下一个安全业务动作时，案件应继续推进，不等待与该动作无关的未来材料。**

材料分为：

- 当前动作必须且已收到；
- 当前动作必须但存在缺漏或质量问题，需要立即澄清；
- 尚未生成，例如警方正式文件，需要记录预计可得时间；
- 仅后续动作需要，可以先创建或路由 claim；
- 冗余或与当前任务无关，不应继续索取。

Agent 必须维护材料状态、通知客户、允许后续在同一 claim 上补充，并避免客户等到后续人工处理时才首次得知缺失。

## 10. 数据、记忆与上下文

不为每个用户建立独立物理数据表。使用共享数据模型，并以 `customer_id`、`claim_id` 和 `session_id` 隔离：

- customer profile 与明确允许保留的沟通偏好；
- claim form 与当前 workflow state；
- session、messages 与压缩后的会话摘要；
- evidence 及其来源、状态和关联字段；
- claim history 查询结果与支持 fraud signal 的证据；
- decisions、handoffs 和可审计的 claim events。

完整对话保存在外部持久层，不在每轮全部发送给模型。每轮只加载当前 claim snapshot、未解决问题、最近必要消息和本轮相关的 policy/history 片段。正式 claim 记录、用户偏好与模型工作记忆必须分开管理，并支持相隔 8-10 天后的 session 恢复。

## 11. Policy、分流与治理

- Agent 必须能查询 AWS 提供的结构化 policy 数据和 anonymised policy documents；RAG 或数据库结果必须返回支持判断的具体依据，检索结果是证据，不是无限授权。
- Coverage 或 excess 不明确时，在相关高影响动作前交给 Claims Professional。
- Severity 用于 fast-track、standard 或 complex 路由，并接受 claims staff 盲审。
- Fraud signal 必须附支持信息，仅触发专业复核；不得自动指控用户或把 signal 当成结论。
- Assessor booking 是条件动作，不与某一 severity 等级机械绑定。
- 紧急路径只识别明确安全信号并升级，不进行医疗诊断或假装已联系紧急服务。

## 12. 内部 Claim State、Tag 与 Workbench

系统必须为企业端用户维护可查询、可筛选和可处理的 Claim Operations Workbench。Workbench 直接来自 `claim state + evidence + decisions + handoffs + events`，不得要求员工重复录入另一份 claim 状态。

内部分类必须区分：

- **结构化状态属性**：severity、coverage、evidence、customer support、urgency、workflow state 和 next action；
- **运营 tag**：awaiting customer、awaiting external document、SLA overdue、staff action required 等队列提示；
- **高影响 signal**：fraud review、duplicate suspected、coverage review 等带证据的专业复核请求；
- **客户可见状态**：用清晰语言解释进度和下一步，不暴露内部敏感 signal。

每个内部 tag 或 signal 至少包含：

```text
code
category
visibility: internal | shared | customer_visible
source: rule | model | document | staff
evidence_refs
confidence
status: proposed | confirmed | dismissed | resolved
requires_action
assigned_queue
created_at
reviewed_at
```

Agent 可以提出 tag 或 signal；高影响内容必须允许员工确认、驳回、覆盖或解决，并保留完整审计记录。`fraud_review_required` 只能表示需要复核，不能变成 `fraudulent` 结论。

Workbench 至少支持：

- Urgent、New/Untriaged、Ready to Progress、Awaiting Evidence、Professional Review、Ready to Create 和 Created/Routed 视图；
- 按状态、tag、priority、assignee、next action 和 SLA 筛选；
- 查看 claim form、材料、来源、冲突、handoff packet 和客户沟通；
- 分配处理人、确认或覆盖 proposed 状态、完成下一动作；
- 将员工处理结果写回 claim state，并向 claimant 同步适当的状态更新。

## 13. Claim 创建与后续说明

FNOL 核心终点是创建并路由一个完整、可继续处理的 claim record。材料可以按 next-action-ready 规则处于未来待补状态，但当前已知事实、来源、证据状态、内部属性、专业复核需求、下一动作和后续责任必须被完整记录。

结束或暂停时，客户至少获得：

- claim number 或明确的创建状态；
- 当前完成到哪里；
- 现在是否需要行动；
- 尚待生成或补充的材料；
- 下一步由 Agent、客户或 Northwind 哪一方负责；
- 预计时间和恢复会话方式。

## 14. 成本与成功指标

### Claimant effort

- 完成时间和问题数量；
- 重复问题、重复解释和重复上传次数；
- form 纠正次数及未解决误解；
- 对当前状态和下一步的理解；
- Agent 接纳率与人工请求原因。

### Human effort

- **事件/执行开销**：人工介入次数、处理时长、转派次数、follow-up 次数和首次有效动作时间；
- **认知开销**：人工理解 initial claim、核对来源、重建上下文和识别未决问题所需时间；
- 人工介入率及原因；
- 转交前已完成的有效信息比例；
- 接手后重复询问或补录次数。

### Agent cost

- 每轮和每宗 claim 的 input/output tokens；
- 检索、摘要和工具调用开销；
- 上下文压缩比例；
- 每个 next safe action 和每个成功 claim 的模型成本；
- 延迟、错误和重试。

### Brief 验收

- 最终 working proof 覆盖 10 个测试场景：5 motor、3 home、2 contents；
- 至少 80% 无需后续补充信息即可完成；
- severity 由 claims staff 盲审；
- 测试集 fraud flag 不出现 false positive；
- instructor role-play 少于 5 分钟、少于 10 个问题。

这些最终验收指标不能被未经验证地转换为 ROI 承诺。

## 15. 数据与集成边界

- AWS mentor 当前扮演 Northwind 负责人的 scenario stakeholder，主要从业务角度回答场景、需求和价值问题，不默认承担技术顾问职责。
- AWS 是否提供数据集、policy 文档、云环境、具体云服务或使用额度均不得预设为可用；只有实际确认 access、schema、permission 和限制后，才能写入实现能力。团队负责检查、映射、接入和验证，不把未确认的数据获取写成产品承诺。
- 原型使用 anonymised policy documents、历史 claim 数据及 mock claims/assessor systems。
- 语音能力待确认；文字、图片和 PDF 属于核心输入。
- 生产级 IAM、隐私、保留、审计和系统可用性必须在后续实现中明确，Prototype 至少要保持数据隔离、来源和日志边界。

客户信息的安全和隐私不能只由创建 claim 前的一个 consent 复选框解决。系统至少应
分别处理：收集前说明用途；Agent 提取内容时区分客户原话、材料内容和模型推断；创建
claim 前确认将保存的关键事实；调用第三方服务前说明共享对象、字段和目的；人工转交
时区分客户可见内容与内部 signal；跨会话恢复、保留和删除时说明保存范围和期限。每次
同意、撤回或共享决定都应与对应的用途、数据范围和 claim event 关联，并且客户端、浏览器
存储和普通错误日志不得暴露不必要的个人信息。

## 16. Prototype 与后续实现原则

Sprint 1 Prototype 必须**路径覆盖完整、实现深度受控**：所有核心行为分支都能端到端演示，但可使用受控场景、有限规则、已确认可用的数据和 mock integration。后续 Sprint 提升场景广度、准确率、韧性、安全性、评估和生产集成，不应改变本文件的产品主张。

### 两个 Key Features

项目以两个相互连接的 Key Features 形成完整产品价值。它们也是叙事层次，但不是先后
隔离的开发阶段，实际实现必须同时考虑并逐步推进。

**Key Feature 1：可信、自适应的理赔入口。** 通过友好、主动且适应客户处境的引导，
把自然语言事故描述转化为有依据、可继续处理的 claim；系统在内部完成专业结构化，
只在必要时让客户确认关键事实，并根据情况自动推进或携带上下文转交人工。它使客户
不必先学会保险流程，也不必逐字段维护一份内部表单。同时，Agent 也服务于 staff：
向 staff 提供带来源、带不确定性和待处理事项的结构化上下文，支持 staff 追问、修正、
拒绝或覆盖建议，减少重读记录和重复询问，并提升 staff 对 Agent 的信任和使用意愿。

**Key Feature 2：基于统一 Claim Context 的理赔协同层。** 以同一份可信 claim context
连接保险公司、工作人员、证据来源和服务商，逐步减少客户自行协调、重复说明和追踪
进度的工作。它把第一项能力从报案入口扩展为连续的理赔服务旅程。

第二层不是把外部服务做成一排入口，而是让系统知道当前 claim 下一步需要谁、需要
什么信息、由谁授权，并在客户同意后完成连接。客户和 staff 两端都必须看到与各自任务
相符的服务状态：客户看到共享范围、进度和下一步，staff 看到请求详情、处理结果、失败
原因和待判断事项。可能的参与方包括理赔工作人员、保单
和核心理赔系统、assessor、维修服务商、拖车或道路救援、警方文件提供方、预约和
付款系统、broker、合规、隐私及审计人员。每次扩展都必须继续使用同一份可信上下文，
并实际推进下一步，而不是只增加页面或展示性的集成。

判断方向是否正确的标准保持不变：客户是否以更自然、更低负担的方式完成当前步骤；
Agent、工作人员和外部参与方是否基于同一份连续、可追踪的上下文继续工作；系统是否
真正推进了一次业务动作；自动化扩展时是否仍保留客户控制、人工判断和安全边界。

## 17. 已知约束与待确认决策

- AWS 数据和 mock services 的实际 schema、访问方式与可用性暂不可知；团队在取得数据后负责映射和接入。
- 当前项目是具有真实交付预期的实习项目，不是竞赛项目；AWS mentor 的角色是 Northwind 业务方 stakeholder，不能把 AWS 资源或数据可用性当作默认前提。
- 技术栈由团队决定，部署目标是 AWS 提供的云端环境；代码仓库名称曾确定为 `Northwind-FNOL-agent`，但当前远端存在性需要重新确认，具体分支和 CI 约定待团队确定。
- 五名成员按工作流进度灵活领取任务，不绑定固定能力岗位；reviewer 按具体任务动态选择。
- 多成员汇流图使用 draw.io 制作，保留 `.drawio` 源文件并导出 SVG；最终节点为 Prototype Delivery，slide 尺寸待定。
- 用户首次请求人工时是否立即转交，或允许 Agent 提供一次透明选择，仍需确认；重复请求、紧急、distress 或无障碍需要必须立即转交。
- 语音是否进入核心范围仍需确认。
- coverage、severity、fraud signal、assessor booking 的具体受控规则需结合 AWS 数据和导师反馈确认。

## 18. 完整 VP 业务旅程

Sprint 3 VP 的完整业务结果不是单独展示 claimant、Workbench 或 Agent 的某一项能力，而是让三者围绕同一份 Claim Context 完成一条连续、可追踪、可恢复的理赔旅程：

```text
用户登录或匿名进入
→ 用自然语言向 Agent 描述案件
→ Agent 根据内容重建 Dynamic Form
→ 用户确认、补充、上传材料
→ Agent 根据案件需要提供第三方服务卡片或协助
→ 用户完成 Claim，持续看到办理进度
→ 用户请求人工或表达需要转人工
→ 带有状态、tag、缺失信息和风险 signal 的 Claim 进入 Workbench
→ 系统将 Claim 动态分配给在线员工
→ 员工领取并处理 Claim
→ 员工可使用 Staff Agent、继续与用户沟通、调用允许的第三方服务
→ 员工将 Claim 推进到下一状态
→ Claim 进入处理中、等待材料、等待用户、已完成等对应队列
```

### 18.1 Claimant 入口与对话

用户可以登录，也可以不登录直接开始报案。匿名用户不得因缺少 bearer token 而被阻塞：系统先创建匿名 session 和 working claim，并在本次会话内允许用户继续对话、上传材料和请求人工支持。匿名 session 的长期持久化、profile 和聊天历史保存范围必须明确；用户在本次会话内登录或注册后，系统应将当前 session 和 Claim 提升并关联到用户，否则匿名数据保持孤立。

Agent 是 claimant 的主要入口。用户可以用自然语言描述事故、盗窃、损坏或其他情况，不需要先理解保险表单。Agent 从用户语言和材料中提取事实，依据已确认事实、未完成事项和当前安全动作持续重建 Dynamic Form，并让用户确认、修正或补充。用户应始终知道已经记录了什么、还缺什么、当前进度如何以及下一步由谁负责。

### 18.2 Dynamic Form、材料和进度

Dynamic Form 是 Claim Context 的可见投影，不是一次性固定问题清单。Agent 应只提出当前动作需要的问题，避免重复询问已经确认的事实；用户可以在已记录信息区域中修改字段，也可以直接用自然语言纠正。

用户可以通过对话工具栏上传图片、PDF 和其他支持的材料。上传、处理、成功、失败、重试和不可用状态都必须真实反映后端记录；文件与 Claim、session、Evidence 和来源保持关联。Agent 应根据材料状态说明还缺什么、哪些材料正在生成、哪些材料只影响后续动作，并在安全的情况下继续推进不依赖该材料的工作。

### 18.3 第三方服务与 stakeholder 协作

当案件需要外部参与方时，例如联系警方取得警方报告、联系维修方或请求评估，Agent 应在相关回复消息正下方展示与该服务对应的卡片或入口，而不是把第三方服务做成脱离对话的独立页面。不同 stakeholder 可以提供不同形式的服务：电话、网页跳转、表单、人工转接、API 或由 Agent 协助填写工单并返回文件。

每项服务都必须明确：

- stakeholder 是谁；
- 可以提供什么服务、材料或信息；
- 需要哪些输入字段；
- 将共享哪些数据以及为什么共享；
- 哪些动作需要 claimant consent 或 staff authority；
- request、processing、accepted、failed、timeout 和 unknown outcome 的含义；
- claimant 和 staff 各自能看到什么；
- 没有企业 access 时如何在同一 adapter 契约下进行清晰仿真。

Agent 可以建议服务、解释服务和请求授权，但不能把建议说成已经发送或已经完成。Runtime 负责决定请求是否可以执行、实际执行、记录结果并处理失败、重试和未知结果。

### 18.4 Handoff 与 Workbench 进入

用户可以点击 Staff Assistance，也可以直接用自然语言表达需要人工帮助。Agent 不应反复阻止合法的人工请求，而应携带当前 Claim Context、已确认字段、缺失事项、材料状态、相关 tag、risk signal 和转交原因进入 Workbench。

handoff 后 claimant 端应看到等待交接、已接手、需要补充、第三方处理中、失败或下一步等状态；用户不需要重新描述已经提供的信息。handoff 不是 Claim 的终点，而是从自助对话转入人工协同的连续状态变化。

### 18.5 Staff Workbench 处理

Workbench 是 Claim State、Evidence、decisions、handoffs 和 events 的工作投影，不是员工另行维护的第二套 Claim 状态。当前已有队列、详情、tabs、Claim conversations 和 Staff Agent 基础，但完整 VP 仍需要补齐真实运营流程：

- 根据后端投影把 Claim 动态分配给在线员工；
- 员工领取 Claim，并处理并发、cowork、移交和 revision 冲突；
- 在同一工作区查看 claimant 对话、Claim Context、字段、材料、来源、第三方记录和 handoff 信息；
- 员工可以使用 Staff Agent 获取带来源的建议；
- 员工可以继续与用户建立实时或等价的持续沟通 session；
- 员工可以在授权范围内调用第三方服务、代用户取得材料或提交工单；
- 员工可以确认、修正、拒绝或覆盖允许修改的内容，并将结果写回权威 Claim State；
- 员工可以将 Claim 标记为下一状态。

Workbench 必须有反映真实生命周期的队列或分类，至少包括处理中、等待用户、等待材料、等待第三方、需要人工动作和已完成。已完成 Claim 不能只停留在当前工作列表中；等待材料或等待用户的 Claim 也不能继续伪装成普通待处理 Claim。

### 18.6 Staff Agent 与正式业务动作

Staff Agent 可以读取员工有权访问的多个 Claim、Claim conversations、Evidence、RAG、policy/history、handoffs、staff actions、customer updates 和第三方记录。它可以生成 claimant message、internal note 或 external request draft，但 draft 不是正式业务动作。

只有在员工明确确认后，draft 才能交给 Runtime 进行权限、revision、idempotency、来源和风险检查。Runtime 执行后必须记录 approved、rejected、executed、failed 或 unknown outcome，并把安全的结果投影回 Workbench、Claimant 和审计记录。

### 18.7 Claim 生命周期

如果用户填到一半放弃对话、承诺补充材料后没有后续，或没有明确的下一步推进动作，系统应暂存为 incomplete Claim。它仍然是 Claim，允许员工在低优先级分类中查看，不应被折叠或丢弃。

incomplete Claim 必须支持：

- 保存已确认信息和当前 session 上下文；
- Agent 或员工跟进；
- 用户恢复并继续；
- 用户补充材料后回到正常处理队列；
- 用户明确放弃；
- 达到 retention 阈值后删除或匿名化；
- 每次 follow-up、恢复、放弃和清理都有可审计记录。

### 18.8 Control Plane

系统管理员或技术运维通过独立的 Control Plane 管理产品运行所需的系统配置、知识、模型、Agent 规则、外部集成、评估、员工和客户账户、runtime profile、运行状态以及 revision、validation、publish、withdraw、rollback 和 audit。Control Plane 是持续扩展的开放式主功能，不是一次性的配置页面；新的实际配置需求应继续纳入同一套版本和权限边界。

### 18.9 业务旅程的实现原则

- Claimant、Agent、Workbench 和 Control Plane 必须围绕清晰的状态、权限和来源工作；
- Agent 负责理解、检索、提出建议和选择候选动作；
- Runtime 负责授权、执行、持久化、审计和决定建议能否改变真实业务状态；
- 前端不能自行计算 Claim State、priority、tag、权限或 provider 成功；
- fixture 只能用于确定性测试，不能替代真实运行证据；
- motor、home、contents 是 VP 验证范围，不是产品永久只支持的三种类型；
- 业务旅程的成功标准是用户、员工和系统都能从当前状态进入可解释、可恢复的下一安全步骤。
- token 与人工 effort 的基线和目标值仍需通过 Prototype 测量。
