# Sprint 3 Week 6 Kanban Draft

## 文档定位

本文件把 Week 6 当前确认的 8 个前置功能块和 10 个实现功能块转换为父 Issue 与 Sub-issue 草案。它不是最终 GitHub Issue 文案，也不创建 Issue、PR 或 Kanban 项目卡。

本周以每人周总工时 36 小时为核算基准：周一至周四各安排 8 小时、周五安排 4 小时；允许同一天的卡片工时不均衡，以保持连贯工作。每人周四下午固定投入 3 小时 presentation，功能开发与收尾合计 33 小时。每张卡的工时表示该 assignee 在这张卡上的 card effort；多人 Sub-issue 分别计算每位 assignee 的工时。父 Issue 工时等于其所有 Sub-issue 工时之和。单个 Sub-issue card 不超过 5 小时。

实际可安排的时间窗口为：

- 周一：功能卡；
- 周二：功能卡；
- 周三：功能卡；
- 周四上午：3 小时功能卡；
- 周四下午：5 小时工作安排，其中每人 3 小时 presentation 排练、2 小时功能卡；
- 周五上午：presentation，不安排开发卡；
- 周五下午：4 小时功能卡，用于演示后修正、运行证据、文档和下一 sprint 输入。

不设置独立 review、fixture 或整体验证父 Issue。测试、失败路径和运行证据属于对应功能卡的交付物。

## 一、父 Issue 总表

| 编号 | 父 Issue 功能块 | High-level 产品结果 | 负责人 | Sub-issue 总工时 |
| --- | --- | --- | --- | ---: |
| P1 | 场景与账号数据包 | 系统拥有一套可运行的 claimant、staff、profile、在线员工和初始 Claim 数据，能够支撑完整 VP 旅程。 | liyang6620 | 6h |
| P2 | 三类 VP 的 Claim 字段与 Dynamic Form 数据 | motor、home、contents 有可供 Agent 和 Workbench 使用的场景字段、确认规则和缺失信息数据。 | liyang6620 | 6h |
| P3 | Third-party / Stakeholder 调研与服务定义 | 团队拥有带来源的 stakeholder、服务、材料、输入和服务形式事实包，并融合 LLL263 与 jxu316-arch 的研究结果。 | LLL263 + jxu316-arch | 12h |
| P4 | RAG 知识库和来源数据包 | Agent 和 Staff Agent 可以使用适用于三类场景、带来源和限制说明的保险知识材料。 | liyang6620 | 6h |
| P5 | Consent 内容和共享数据定义 | 每种第三方服务都有清晰的共享数据、用途、授权、拒绝和撤回规则，并融合双方资料。 | LLL263 + jxu316-arch | 12h |
| P6 | Agent Context、对话历史和行为定义 | Agent 的上下文、历史范围、六类行为、提示词和动作边界可直接用于后续实现。 | Ysoseri1224 | 7h |
| P7 | Tag 语义和场景投影数据 | 现有 Tag Registry 被正确映射到三类场景、来源、可见范围和 Workbench 展示语义。 | Ysoseri1224 | 6h |
| P8 | 模拟案件材料包 | 三类 VP 拥有可演示的图片、文档、报告和 Evidence 关联材料，且不混入测试专用 fixture。 | bdfa123 | 14h |
| P9 | Claimant 文件上传完整功能 | 用户可以从 claimant 对话上传文件，看到真实状态，且 Agent 和 Claim Context 能继续使用上传结果。 | liyang6620 | 8h |
| P10 | Agent 动态收集和进度反馈 | Agent 能根据用户消息更新字段、提出当前问题、接受纠正并说明 Claim 进度。 | Ysoseri1224 | 7h |
| P11 | 第三方服务接入完整功能 | 用户和员工可以从 Agent 旅程中使用已定义的第三方服务，并看到请求、结果和失败状态。 | bdfa123 | 19h |
| P12 | Handoff 到 Workbench 的完整功能 | 用户请求人工后，Claim 携带完整上下文、状态和原因进入 Workbench，员工可以继续处理。 | jxu316-arch | 11h |
| P13 | Workbench 动态分发和领取 Claim | Claim 能根据后端投影进入可处理队列、分配给在线员工并安全地被员工领取。 | liyang6620 | 7h |
| P14 | Workbench 的处理中和已完成队列 | 员工推进 Claim 后，案件能进入处理中、等待用户、等待材料、等待第三方或已完成等正确位置。 | LLL263 | 17h |
| P15 | 员工处理 Claim 的完整操作流程 | 员工能在同一工作区查看上下文、沟通、调用服务、修改允许字段并推进 Claim。 | jxu316-arch | 7h |
| P16 | Staff Agent 的实际业务动作 | Staff Agent 的 draft 经员工确认后，可以变成受 Runtime 授权、执行和审计的正式动作。 | Ysoseri1224 | 5h |
| P17 | Incomplete Claim 系列功能 | 中断的 Claim 可以暂存、跟进、恢复、放弃或按 retention 规则清理，并保持可审计。 | jxu316-arch | 7h |
| P18 | Control Plane 持续扩展 | 管理员可以在现有 Control Plane 中持续管理系统配置、知识、模型、Agent 规则、外部集成、账户、评估和运行状态。 | Ysoseri1224 | 8h |

### 每人周工时核算

| 成员 | 功能 Sub-issue 合计 | 周四 presentation | 本周合计 | 目标 |
| --- | ---: | ---: | ---: | --- |
| liyang6620 | 33h | 3h | 36h | 周总工时达标；日内允许不均衡 |
| LLL263 | 33h | 3h | 36h | 周总工时达标；日内允许不均衡 |
| jxu316-arch | 33h | 3h | 36h | 周总工时达标；日内允许不均衡 |
| Ysoseri1224 | 33h | 3h | 36h | 周总工时达标；日内允许不均衡 |
| bdfa123 | 33h | 3h | 36h | 周总工时达标；日内允许不均衡 |

18 个功能父 Issue 的 Sub-issue 合计为 165h；P19 presentation 合计为 15h；全队本周 Kanban 工时为 180h。

## 二、前置功能块 Sub-issue

### P1. 场景与账号数据包｜负责人：liyang6620｜总工时：6h

High-level 描述：系统拥有一套可运行的 claimant、staff、profile、在线员工和初始 Claim 数据，能够支撑完整 VP 旅程，而不是只有孤立的测试账号。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P1.1 盘点现有身份、Claim、session、message 和 evidence 字段，列出可复用与缺失项 | liyang6620 | 3h | 周一 | 当前代码可直接使用的字段清单和缺口说明。 |
| P1.2 写入 claimant、staff、profile、在线员工和三类初始 Claim 的可运行 mock 数据关系 | liyang6620 | 3h | 周二 | 可被 claimant、Workbench 和 Agent 旅程读取的业务数据，不新增孤立临时账号。 |

非目标：不重新设计身份体系，不建立第二套 Claim State，不把数据写成测试专用 fixture。

### P2. 三类 VP 的 Claim 字段与 Dynamic Form 数据｜负责人：liyang6620｜总工时：6h

High-level 描述：motor、home、contents 有可供 Agent 和 Workbench 使用的场景字段、确认规则和缺失信息数据，并复用现有 Field/Branch Registry。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P2.1 将现有 registered fields 和 branches 映射到三类 VP 场景，标出可复用和缺失字段 | liyang6620 | 3h | 周一 | 场景字段映射和实际缺口列表。 |
| P2.2 补齐字段示例、确认状态、当前动作需求和 Workbench/claimant 投影输入 | liyang6620 | 3h | 周二 | 可供 Agent 和 API 使用的场景化字段数据。 |

非目标：不从零重建 Field Registry，不由前端自行维护字段或动态表单状态。

### P3. Third-party / Stakeholder 调研与服务定义｜负责人：LLL263 + jxu316-arch｜总工时：12h

High-level 描述：团队拥有带来源的 stakeholder、服务、材料、输入和服务形式事实包，并融合双方研究结果，作为后端和 Agent 实现的确定输入。

这是本周明确允许交叉的资料任务。LLL263 与 jxu316-arch 必须互相审阅对方的研究，指出冲突、未知项和未经证实的假设，再形成一份融合后的结果；不能各自提交两份互不相容的目录。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P3.1 收集警方、维修方、评估方及其他真实 stakeholder 的服务事实和来源 | LLL263 | 5h | 周一 | 第一份 stakeholder/service research notes。 |
| P3.2 独立复核 stakeholder、服务形式、可获取材料和访问限制，提出反例与未知项 | jxu316-arch | 2h | 周一 | 带质疑和边界的独立复核 notes。 |
| P3.3 互审并融合为统一服务目录和实现 brief | LLL263 + jxu316-arch | 2h each | 周二 | 一份统一的 stakeholder、capability、service form、input、output 和 failure brief。 |
| P3.4 补齐 P3.1 未覆盖的 stakeholder 事实、来源和访问限制 | LLL263 | 1h | 周二 | 完整的第一方研究输入，供双方融合。 |

非目标：不在本卡中决定 Agent prompt、数据库 schema、前端布局或实际 adapter 实现。

### P4. RAG 知识库和来源数据包｜负责人：liyang6620｜总工时：6h

High-level 描述：Agent 和 Staff Agent 可以使用适用于三类场景、带来源和限制说明的保险知识材料，而不是只调用一个空 retriever。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P4.1 盘点现有 governed sources，确定三类 VP 所需的 policy、流程和材料知识 | liyang6620 | 3h | 周二 | source、version、section 和适用范围清单。 |
| P4.2 准备并接入带引用的 mock knowledge documents，包含 no-result、ambiguous 和 unavailable 场景 | liyang6620 | 3h | 周三 | 可供现有 RAG adapter 使用的知识数据和来源记录。 |

非目标：不把 mock knowledge 写成真实 Northwind policy，不宣称真实 policy provider 已接入。

### P5. Consent 内容和共享数据定义｜负责人：LLL263 + jxu316-arch｜总工时：12h

High-level 描述：每种第三方服务都有清晰的共享数据、用途、授权、拒绝和撤回规则，并融合双方资料，供 claimant、staff、Agent 和 Runtime 使用。

LLL263 与 jxu316-arch 在本块中同样需要互审和融合：LLL263 负责以用户可理解的语言整理服务和共享内容，jxu316-arch 负责核对 authority、record/send 区分、撤回和审计边界，最终必须合成一份统一结果。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P5.1 按服务整理用户可理解的共享数据、用途和 consent 文案 | LLL263 | 5h | 周二 | claimant-facing consent notes。 |
| P5.2 核对 record permission、send permission、staff authority、撤回和审计要求 | jxu316-arch | 2h | 周二 | authority/privacy boundary notes。 |
| P5.3 互审并融合为服务级 consent 与共享数据契约 | LLL263 + jxu316-arch | 2h each | 周三 | 每个服务一份共享字段、用途、授权、拒绝、撤回和记录规则。 |
| P5.4 补齐服务级共享数据和用户可理解文案的遗漏项 | LLL263 | 1h | 周一 | 可进入融合结果的补充 consent notes。 |

非目标：不自行实现 consent API，不把单个前端勾选框当成完整隐私控制。

### P6. Agent Context、对话历史和行为定义｜负责人：Ysoseri1224｜总工时：7h

High-level 描述：Agent 的上下文、历史范围、六类行为、提示词和动作边界可直接用于后续实现，并能支持 claimant 与 staff 的连续旅程。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P6.1 定义一轮 claimant/staff Agent 可读取的 Claim Context、消息历史和来源范围 | Ysoseri1224 | 5h | 周一 | context、history、privacy 和 source boundary。 |
| P6.2 定义六类 Agent 行为、工具调用、Dynamic Form 更新、handoff 和正式动作边界 | Ysoseri1224 | 2h | 周二 | 可供 Runtime 和 prompt 实现使用的行为/action brief。 |

非目标：不在本卡中实现数据库 adapter，不让 prompt 直接获得业务授权。

### P7. Tag 语义和场景投影数据｜负责人：Ysoseri1224｜总工时：6h

High-level 描述：现有 Tag Registry 被正确映射到三类场景、来源、可见范围和 Workbench 展示语义，而不是创建第二套前端标签。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P7.1 将现有 staff-facing tags 映射到 motor、home、contents 的真实场景和材料状态 | Ysoseri1224 | 4h | 周二 | 场景 tag mapping 和未覆盖项。 |
| P7.2 明确 tag 的来源、可见范围、风险等级、激活条件和 Workbench 显示语义 | Ysoseri1224 | 2h | 周三 | 与现有 registry 一致的 projection brief。 |

非目标：不重新创建 Tag Registry，不把 fraud signal 写成 fraud 结论，不让前端自行决定 tag。

### P8. 模拟案件材料包｜负责人：bdfa123｜总工时：14h

High-level 描述：三类 VP 拥有可演示的图片、文档、报告和 Evidence 关联材料，且不混入测试专用 fixture。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P8.1 按 motor、home、contents 列出完整演示材料清单和文件命名规则 | bdfa123 | 5h | 周一 | 演示材料目录和每项用途。 |
| P8.2 准备车辆、房屋、物品图片以及警方报告、维修单、评估报告等模拟材料 | bdfa123 | 5h | 周二 | 可用于 VP 运行的材料文件。 |
| P8.3 为材料补充 Claim、Evidence、来源和状态关联，明确产品运行数据与测试 fixture 的边界 | bdfa123 | 4h | 周三 | 可被后端和演示旅程读取的材料关系。 |

非目标：不设计第三方服务契约，不提交单功能临时 fixture，不修改 CI。

## 三、功能实现块 Sub-issue

### P9. Claimant 文件上传完整功能｜负责人：liyang6620｜总工时：8h

High-level 描述：用户可以从 claimant 对话上传文件，看到真实状态，且 Agent 和 Claim Context 能继续使用上传结果。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P9.1 接通现有上传接口、Evidence 元数据保存和 Claim/session 关联 | liyang6620 | 4h | 周二 | 上传请求、保存和归属链路。 |
| P9.2 接入 claimant 上传状态、处理中/失败/重试和 Agent 可见结果 | liyang6620 | 3h | 周三 | 对话中的真实上传状态和后端结果投影。 |
| P9.3 补匿名 session、大小/类型错误和不可用存储边界 | liyang6620 | 1h | 周四上午 | 匿名与失败路径不阻塞合法对话。 |

### P10. Agent 动态收集和进度反馈｜负责人：Ysoseri1224｜总工时：7h

High-level 描述：Agent 能根据用户消息更新字段、提出当前问题、接受纠正并说明 Claim 进度。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P10.1 将用户消息映射到已注册字段，并保留确认、推断、缺失和冲突状态 | Ysoseri1224 | 3h | 周二 | Agent 与 Dynamic Form 的真实更新行为。 |
| P10.2 展示还需要什么、当前动作是什么和 Claim 已完成到哪里 | Ysoseri1224 | 2h | 周三 | claimant 进度反馈和下一步表达。 |
| P10.3 支持自然语言纠正、字段确认和 motor/home/contents 的路径差异 | Ysoseri1224 | 2h | 周四上午 | 三条 VP 的纠正和进度行为。 |

### P11. 第三方服务接入完整功能｜负责人：bdfa123｜总工时：19h

High-level 描述：用户和员工可以从 Agent 旅程中使用已定义的第三方服务，并看到请求、结果和失败状态。

开始条件：P3 和 P5 的融合结果已完成；未完成前不得创建依赖其字段和状态的 PR。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P11.1 按批准的 service brief 实现一个具体服务的请求状态转换 | bdfa123 | 5h | 周三 | prepared、accepted 和明确失败状态。 |
| P11.2 接通服务请求、响应和来源类型，保持 simulated/configured/live-attempted 区分 | bdfa123 | 5h | 周三 | 后端服务调用和来源投影。 |
| P11.3 接入 Agent 消息下的服务卡片、按钮或表单入口及状态反馈 | bdfa123 | 5h | 周四上午 | claimant/Workbench 可使用的服务入口。 |
| P11.4 实现 timeout、unavailable、malformed、unknown outcome 和恢复路径 | bdfa123 | 4h | 周五下午 | 明确失败、重试或 reconcile 结果，不丢失 Claim 进度。 |

### P12. Handoff 到 Workbench 的完整功能｜负责人：jxu316-arch｜总工时：11h

High-level 描述：用户请求人工后，Claim 携带完整上下文、状态和原因进入 Workbench，员工可以继续处理。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P12.1 形成包含原因、已确认字段、缺失信息、材料和 tag/signal 的 handoff packet | jxu316-arch | 4h | 周三 | 可供 staff 继续处理的交接上下文。 |
| P12.2 实现 handoff 状态、权限、revision 和 Claim 进入 Workbench 的后端边界 | jxu316-arch | 5h | 周四上午 | handoff 真实写入和冲突处理。 |
| P12.3 将等待交接、已接手和下一步状态投影给 claimant 与 Workbench | jxu316-arch | 2h | 周五下午 | 双端状态连续，不重复收集信息。 |

### P13. Workbench 动态分发和领取 Claim｜负责人：liyang6620｜总工时：7h

High-level 描述：Claim 能根据后端投影进入可处理队列、分配给在线员工并安全地被员工领取。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P13.1 根据后端 priority、tag、缺失信息和 next action 生成可分发的 Claim projection | liyang6620 | 2h | 周二 | 不由前端自行排序的分发输入。 |
| P13.2 实现在线员工池、领取 Claim 和责任记录 | liyang6620 | 3h | 周三 | 员工可领取并开始处理的真实动作。 |
| P13.3 处理重复领取、revision 冲突、requeue、cowork 或移交边界 | liyang6620 | 2h | 周四上午 | 并发和失败路径。 |

### P14. Workbench 的处理中和已完成队列｜负责人：LLL263｜总工时：17h

High-level 描述：呤工推进 Claim 后，案件能进入处理中、等待用户、等待材料、等待第三方或已完成等正确位置。

开始条件：P13 的后端 projection 和 P12/P17 的状态字段已经明确；本块只负责已有 Workbench 的受限接入，不自行定义状态。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P14.1 将处理中、等待用户、等待材料和等待第三方映射到已有 Workbench 导航和列表 | LLL263 | 5h | 周三 | 员工能找到不同生命周期中的 Claim。 |
| P14.2 增加已完成、放弃/关闭的收纳位置和返回流程 | LLL263 | 4h | 周四上午/周四下午（2h/2h） | 完成 Claim 不再留在普通处理列表。 |
| P14.3 补 loading、empty、unavailable、conflict 和 action failure 的页面状态 | LLL263 | 5h | 周五下午 | 页面不隐藏真实失败，也不创建前端私有状态。 |
| P14.4 收口 P14.1 的剩余生命周期映射与列表入口 | LLL263 | 1h | 周四上午 | 处理中和等待类队列的映射完整闭合。 |
| P14.5 收口已完成、放弃/关闭队列的剩余返回与状态提示 | LLL263 | 2h | 周五下午 | 完成和关闭类 Claim 的入口与状态表达闭合。 |

### P15. 员工处理 Claim 的完整操作流程｜负责人：jxu316-arch｜总工时：7h

High-level 描述：呤工能在同一工作区查看上下文、沟通、调用服务、修改允许字段并推进 Claim。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P15.1 形成员工处理 Claim 时可查看和可操作的完整上下文清单 | jxu316-arch | 3h | 周三 | Claim、conversation、field、material、source、handoff 和 action 范围。 |
| P15.2 接入员工与 claimant 的持续沟通 session 和发送边界 | jxu316-arch | 2h | 周四上午 | 员工可以继续沟通而不创建错误的孤立 session。 |
| P15.3 接入员工允许的第三方操作、字段更新和下一状态写回 | jxu316-arch | 2h | 周五下午 | 员工处理结果进入权威 Claim State。 |

### P16. Staff Agent 的实际业务动作｜负责人：Ysoseri1224｜总工时：5h

High-level 描述：Staff Agent 的 draft 经员工确认后，可以变成受 Runtime 授权、执行和审计的正式动作。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P16.1 定义 claimant message、internal note 和 external request draft 的转化规则 | Ysoseri1224 | 2h | 周三 | draft 到候选动作的明确行为契约。 |
| P16.2 接入确认、执行结果、失败/unknown outcome 和 claimant/Workbench 投影 | Ysoseri1224 | 3h | 周四上午 | 员工确认后才能产生正式业务结果。 |

### P17. Incomplete Claim 系列功能｜负责人：jxu316-arch｜总工时：7h

High-level 描述：中断的 Claim 可以暂存、跟进、恢复、放弃或按 retention 规则清理，并保持可审计。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P17.1 持久化 incomplete Claim、恢复上下文和 follow-up task | jxu316-arch | 3h | 周二 | 用户离开后 Claim 不丢失，恢复时不重复收集信息。 |
| P17.2 实现 follow-up、用户恢复、放弃和 retention threshold | jxu316-arch | 2h | 周四上午 | 生命周期动作和权限边界。 |
| P17.3 实现 purge/anonymise、旧 session 访问拒绝和 claimant/Workbench 投影 | jxu316-arch | 2h | 周五下午 | 清理、失败和审计结果。 |

### P18. Control Plane 持续扩展｜负责人：Ysoseri1224｜总工时：8h

High-level 描述：管理员可以在现有 Control Plane 中持续管理系统配置、知识、模型、Agent 规则、外部集成、账户、评估和运行状态。

这是开放式主功能块，从当前正在推进的 Control Plane PR 继续扩展。每个 Sub-issue 只纳入本周实际出现的配置需求，但不能把 Control Plane 缩减成一次性 configuration API 接入。

| Sub-issue | Assignee | 工时 | 时段 | 交付物 |
| --- | --- | ---: | --- | --- |
| P18.1 延续当前 Control Plane PR，完成已确定的 revision、validation、publish、rollback 和 audit 边界 | Ysoseri1224 | 3h | 周一 | 当前 PR 的可运行增量，而不是另起一套管理入口。 |
| P18.2 将本周确定的知识、模型、Agent 规则和外部集成配置需求纳入管理范围 | Ysoseri1224 | 2h | 周二 | 新增配置内容、版本和权限范围。 |
| P18.3 补员工/claimant 账户、runtime profile、评估和运行状态的实际管理入口 | Ysoseri1224 | 2h | 周三 | Control Plane 对实际 VP 运维需求的增量支持。 |
| P18.4 整理失败配置、unavailable provider 和下一 sprint 的未完成配置项 | Ysoseri1224 | 1h | 周五下午 | 诚实的运行状态和后续清单。 |

## 四、共同 presentation 卡

### P19. Presentation rehearsal｜每人 3h｜周四下午

这张卡只安排周四下午每人 3 小时的 presentation 排练，不制作 slides。周四剩余 5 小时仍用于功能开发或收尾，因此每人周四合计 8 小时。

交付内容：

- 按完整 VP 用户旅程排练 claimant、Agent、第三方服务、handoff、Workbench 和 Control Plane 的演示顺序；
- 确认演示账号、初始 Claim、图片/文件、RAG 内容和仿真服务状态；
- 确认失败或 unavailable 时的备用演示路径；
- 确认每个人的讲解与操作边界；
- 记录会阻塞 presentation 的问题，周五下午只修复有限 blocker。

周五上午是正式 presentation，不安排开发卡。

## 五、依赖与执行规则

### 前置数据到功能实现

```text
P1 场景与账号数据
P2 Claim 字段与 Dynamic Form 数据
P3 Third-party 调研与服务定义
P4 RAG 知识和来源
P5 Consent 与共享数据定义
P6 Agent Context、历史和行为
P7 Tag 语义和投影
P8 模拟案件材料
        ↓
P9 文件上传
P10 Agent 动态收集和进度
P11 第三方服务接入
P12 Handoff
P13 Workbench 分发和领取
P14 Workbench 生命周期队列
P15 员工处理 Claim
P16 Staff Agent 正式动作
P17 Incomplete Claim 生命周期
P18 Control Plane 持续扩展
```

上述顺序用于表达可开始条件，不要求所有卡在同一时间启动，也不允许后续负责人用临时字段、私有接口或 fixture 冒充前置依赖已完成。

### Sub-issue 和 PR 规则

1. 每个父 Issue 的描述只写 high-level 产品结果；实现细节放入 Sub-issue。
2. 每个 Sub-issue 只有一个主负责人；P3 和 P5 的 LLL263/jxu316-arch 互审融合是本周明确批准的例外，必须在卡内写清双方各自产出和最终统一结果。
3. Sub-issue 可以涉及全栈，但必须说明它实际改变的页面、API、Runtime、数据、文档和测试范围。
4. 前序 Sub-issue 未完成前，后续负责人只能阅读、准备本地工作或提出依赖问题，不能推送依赖未满足的 PR。
5. 不建立独立 review、fixture 或整体验证卡；测试和运行证据必须随功能卡交付。
6. 不修改 CI 来绕过功能缺口或质量门；不把配置存在、fixture 成功或静态页面存在写成真实 provider 能力。
7. Workbench、Tag Registry、Field Registry、身份系统和 Model Gateway 已有基础，Week 6 只补真实缺口、接入和状态覆盖。
8. 三条 VP 路径是最终验收范围，不是把产品永久限制为 motor、home、contents 三类。

## 六、时间窗口与完成口径

### 周一至周三：3 天功能推进

优先推进前置数据、调研融合、Agent 行为、Control Plane 和已经满足依赖的确定性实现。每张卡必须能在本时间窗口内形成文档、数据、代码、可运行接口或明确失败结果。

### 周四上午：3 小时功能推进

只完成可以在上午收口的 Sub-issue、依赖收尾和 presentation blocker 预检查，不开启新的大型功能块。周四下午安排 5 小时工作，其中每人 3 小时 presentation、2 小时功能卡；周四全天合计 8 小时。

### 周四下午：每人 3 小时 presentation 排练

只执行 P19，不制作 slides，不把排练时间计算进 18 个功能父 Issue 的工时。每人 3 小时，团队合计 15 小时；下午剩余 2 小时可用于功能卡。

### 周五上午：presentation

不安排开发卡。

### 周五下午：4 小时收尾

每人安排 4 小时，只处理有限 blocker 修复、运行证据、状态文档、未完成项和下一 sprint 输入。周五上午是正式 presentation，不安排开发卡；周五全天每人合计 4 小时工作安排。

## 七、父 Issue 完成条件

一个父 Issue 只有在其 Sub-issue 形成完整可观察结果后才算完成。完成不要求所有潜在扩展都实现，但必须：

- 与现有 codebase 和已确认契约一致；
- 不把 fixture、模拟或配置误写成 live 能力；
- 成功、失败、timeout、unavailable 或 unknown outcome 有明确表达；
- 前端、后端、数据和 Agent 行为没有各自维护互相冲突的状态；
- 运行证据、限制和未完成项被记录到对应功能交付物中。

> **Repository-facing card source:** The English contracts below are the canonical detailed descriptions for all Sub-issues. The earlier planning tables are schedule context; when a repository Issue is created or updated, use the matching contract row below.

## VIII. Canonical English Sub-issue Contracts

This matrix is the authoritative source for repository-facing Sub-issue bodies. The earlier shorthand rows remain useful for schedule context, but each Issue body must use the corresponding contract below. Every card is independently executable, has one bounded result, and must not be marked Ready while its listed dependency is unresolved.

| Card | Inputs | Owned change | Observable output | Failure boundary and evidence |
| --- | --- | --- | --- | --- |
| P1.1 | Current identity, Claim, session, message, Evidence models, migrations, routes, adapters, tests | Inventory reusable, missing, ambiguous, and obsolete fields, relationships, source-of-truth and visibility boundaries; link each gap to a downstream card | A source-linked field inventory consumed by P1.2 and later implementation cards | Conflicts stay explicit; no private field choice. Evidence: schema/API references and documented gaps. Non-goal: no second identity or Claim-state system. |
| P1.2 | P1.1 inventory and existing persistence contracts | Seed linked claimant/staff profiles, online staff, sessions, messages, Evidence references, and one initial Claim per representative path | Claimant, Workbench, and Agent can read coherent seeded data through existing APIs | Broken relationships and anonymous persistence limits remain visible. Evidence: API readback plus login-to-Claim smoke journey. Non-goal: no fixture-only product data. |
| P2.1 | Field/Branch Registry, backend schema, representative Claims | Map every registered field to motor/home/contents, branch, visibility, confirmation need, and lifecycle use; list gaps | Versioned scenario mapping for Agent Context and projections | Do not duplicate conflicting names or hide unsupported branches. Evidence: registry/API cross-reference. Non-goal: no frontend-owned form state. |
| P2.2 | P2.1 mapping and field persistence/projection contracts | Add representative values and rules for confirmed, inferred, missing, conflicting, and not-applicable states; define claimant/Workbench projections | Runtime-consumable scenario field data | Unknown or invalid values cannot advance a Claim. Evidence: API examples for all states across three paths. Non-goal: no local completion calculation. |
| P3.1 | Public authoritative stakeholder sources and scenario needs | Research police, repair, assessor, and other stakeholder identity, service, form, inputs, outputs, access constraints, source/date, confidence | Source-linked research notes and fact table | Unverifiable access and missing information are marked unknown. Evidence: source register. Non-goal: no adapter, schema, UI, or prompt implementation. |
| P3.2 | P3.1 notes and independent source review | Challenge service form, material, authority, access, and failure assumptions; identify contradictions and missing stakeholders | Review log with accepted facts, disputed claims, and unresolved questions | Live access and simulation remain separate. Evidence: source-by-source challenge log. Non-goal: no implementation. |
| P3.3 | P3.1 and P3.2 outputs | LLL263 consolidates user-facing service/material facts; jxu316-arch validates authority/access/failure boundaries; both merge one catalogue | Unified service contract: stakeholder, capability, form, inputs, outputs, consent, statuses, provenance, simulation boundary | Conflicts retain owner and unresolved status. Evidence: merged document with both review records. Non-goal: no UI/schema/prompt coding. |
| P3.4 | P3.3 gap and conflict list | Close high-impact unknowns, add sources, and update confidence/access status | Complete brief or explicit bounded blockers for implementation | Unresolved access remains unavailable or simulation-only. Evidence: updated source register/change log. Non-goal: no adapter coding. |
| P4.1 | Governed documents and three scenario mappings | Identify required policy, process, safety, evidence, and material knowledge with source, version, section, authority, and scope | Source coverage matrix for claimant and staff journeys | Outdated, ambiguous, and unavailable content is labeled. Evidence: matrix linked to source records. Non-goal: no invented Northwind policy. |
| P4.2 | P4.1 matrix and current RAG adapter | Prepare cited mock documents and metadata for no-result, ambiguous, and unavailable cases; connect through adapter | Retrieval returns source, version, section, confidence, and availability provenance | No-result never becomes an uncited answer. Evidence: API retrieval and Agent/Staff context readback. Non-goal: no live policy-provider claim. |
| P5.1 | P3 service catalogue and privacy principles | Write plain-English data, purpose, recipient, retention, refusal, and withdrawal copy per service | Claimant-facing consent notes tied to service/data identifiers | Record permission and send permission are separate. Evidence: copy review against every service. Non-goal: no API/runtime implementation. |
| P5.2 | P3 catalogue, P5.1 copy, authorization/audit contracts | Specify record/send permission, staff-mediated authority, withdrawal effect, retention, and audit events | Authority/privacy boundary notes per action type | Refusal, withdrawal, expiry, and overreach are denied explicitly. Evidence: action-to-rule matrix. Non-goal: no direct API implementation. |
| P5.3 | P5.1 and P5.2 | LLL263 checks clarity; jxu316-arch checks authority/audit; both merge one service-level contract | Shared-field, purpose, authorization, refusal, withdrawal, and record rules | Conflicts remain blocked, not defaulted. Evidence: merged contract and review records. Non-goal: no frontend-only consent state. |
| P5.4 | P5.3 omissions and conflicts | Resolve missing fields/copy, align identifiers with P3, record unresolved privacy blockers | Complete consent package or explicit blocked items | Unknown sharing remains unavailable. Evidence: updated contract/change log. Non-goal: no runtime implementation. |
| P6.1 | Claim/session/message/Evidence contracts, P1-P5 outputs, claimant/staff visibility rules | Define context slices, history windows, source precedence, claimant isolation, staff global scope, and unavailable-source representation | Context contract for both Agent runtimes | Stale, conflicting, missing, or inaccessible sources stay labeled. Evidence: claimant Claim scope and staff multi-Claim examples. Non-goal: no authorization bypass. |
| P6.2 | P2, P3, P5, P6.1, Runtime actions | Define triggers/outputs for field collection, correction, progress, RAG, third-party suggestion, handoff, and confirmation | Behaviour/action brief and prompt inputs | Tool refusal, unavailable provider, ambiguity, and unknown outcome are explicit. Evidence: behaviour examples linked to Runtime actions. Non-goal: no prompt-only authorization. |
| P7.1 | Tag Registry, P2 fields, P4 knowledge, P8 material states | Map injury, incident, stakeholder, material, progress, and risk tags to scenarios and evidence conditions | Scenario tag mapping with labels and source conditions | Risk signal is not a fraud conclusion. Evidence: mapping against sample Claims. Non-goal: no second tag system. |
| P7.2 | P7.1 and projection/visibility contracts | Define tag source actor, activation, confidence/risk, claimant visibility, Workbench rendering, and update semantics | Projection brief for backend/frontend | Inferred or stale tags remain marked. Evidence: source/visibility projection examples. Non-goal: no client inference. |
| P8.1 | P2 fields, P3 services, P4 knowledge, journey steps | List every demo image/document/report, scenario, Claim/Evidence purpose, source label, status, and filename | Demonstration material catalogue covering all three paths | Missing/invalid/unavailable material is listed. Evidence: catalogue-to-journey review. Non-goal: no test fixture design. |
| P8.2 | P8.1 catalogue and approved simulation boundary | Produce vehicle, home, contents, police, repair, and assessment images/documents with runtime metadata | Reusable simulation materials for VP | Simulated origin is explicit; no live-provider representation. Evidence: file inspection and Evidence readback. Non-goal: no CI changes. |
| P8.3 | P8.1/P8.2 and Evidence persistence | Associate each material with Claim, Evidence, source, processing state, and status | Runtime-readable Evidence records linked to Claims | Broken association/storage outage is visible and retryable. Evidence: API readback and journey. Non-goal: no temporary fixture commit. |
| P9.1 | Upload route, storage adapter, Evidence model, anonymous-session contract | Connect claimant upload to real API; persist metadata, ownership, Claim/session association | Upload request and metadata chain visible to Claim Context | Invalid type/size, duplicate, anonymous, and unavailable storage outcomes are explicit. Evidence: API/authorization plus browser upload. Non-goal: no local-only state. |
| P9.2 | P9.1 response and Evidence status projection | Render pending, processing, ready, failed, retryable, unavailable; expose ready metadata to Agent and Uploaded Files | Conversation and file view follow server state | Retry is idempotent; failed processing cannot advance required Claim state. Evidence: browser/API transitions. Non-goal: no frontend status generation. |
| P9.3 | Anonymous policy and upload error contract | Preserve conversation while reporting non-persistent anonymous upload outcomes and login/retry boundary | Legitimate anonymous chat remains usable without false persistence | Storage outage, unsupported/oversized file, expired session. Evidence: failure API and browser recovery. Non-goal: no anonymous profile/history persistence. |
| P10.1 | P2 mapping, Claim Context, Agent action contract | Connect extracted candidates to field updates with provenance/status and confirmation for uncertain values | Authoritative field projection aligned with Agent message | Conflicting, unsupported, or ambiguous facts do not overwrite silently. Evidence: three-path API/browser examples. Non-goal: no frontend inference. |
| P10.2 | Required-field projection and current Claim state | Render missing information, next action, progress summary, and updates after accepted fields | Claimant sees what remains and what happens next | Unavailable/contradictory progress is shown as unavailable, not invented percentage. Evidence: incremental browser journey. Non-goal: no local completion calculation. |
| P10.3 | P10.1/P10.2 projections and scenario mapping | Support natural-language correction, confirmation changes, branch follow-up, and recorded-information rerender across all paths | Corrected authoritative values and consistent Agent/UI response | Invalid correction or branch conflict is explained without silent overwrite. Evidence: full motor/home/contents browser journeys. Non-goal: no duplicate scenario component stacks. |
| P11.1 | Merged P3 catalogue, P5 contract, Runtime action registry | Implement one approved service prepared → consent-required/accepted → submitted transition with request identity | Persisted, idempotent authoritative request state | Missing consent, duplicate, and denial cause no silent mutation. Evidence: API/authorization integration. Non-goal: no unapproved provider capability. |
| P11.2 | P11.1 state model and adapter contract | Connect request/response, provenance, source timestamp, and result to Claim/Evidence | Provider-neutral response distinguishes simulated/configured/live-attempted | Timeout, unavailable, malformed, unknown outcomes recover. Evidence: adapter integration/API examples. Non-goal: no unverified live claim. |
| P11.3 | P3/P5 contracts and P11.1/P11.2 API | Render service/provider/purpose/shared-data/consent/request/result/limits and correct link/phone/form/assisted action under Agent message | Claimant and Workbench can submit through Runtime and see projection | Refusal, unavailable, duplicate, unknown keep conversation usable. Evidence: browser action plus API contract. Non-goal: no Agent decision logic/local mutation. |
| P11.4 | P11.2 provenance and error envelope | Implement retry/reconcile, user/staff messaging, request identity preservation, and Claim continuity | Explicit recoverable external-service failure state | Retry idempotent; unknown requires reconciliation, not duplicate submission. Evidence: failure integration/browser journey. Non-goal: no fake success. |
| P12.1 | Claim Context, fields, Evidence, tags/signals, history, handoff reason | Persist handoff packet with source/provenance references and staff-readable reason/gaps/next action | Workbench receives complete packet without repeated intake | Missing context labeled and filtered by staff policy. Evidence: API packet and rendering. Non-goal: no staff hierarchy. |
| P12.2 | P12.1 packet, Claim state, staff auth, revision rules | Authorize and atomically persist handoff state/revision, publish projection, audit event | One authoritative handoff operation | Duplicate, stale, unauthorized, or unavailable projection is explicit. Evidence: authorization/revision/API integration. Non-goal: no client-only handoff. |
| P12.3 | Handoff state and Workbench projection | Render claimant waiting/received state and staff reason/gaps/next action/claimability | Both sides remain continuous after handoff | Projection lag/unavailable is explicit. Evidence: cross-client browser journey. Non-goal: no unlinked session. |
| P13.1 | Authoritative Claim priority/tags/gaps/responsibility/next-action fields | Expose display-ready queue classification and ordering inputs from backend projection | Queue/detail APIs consume one projection | Missing/stale projection is unavailable; frontend does not infer priority. Evidence: API contract/examples. Non-goal: no client sorting algorithm. |
| P13.2 | Online staff availability, auth, projection, responsibility contract | Implement claim/accept action with actor, timestamp, assignment, and resulting projection | One staff member safely takes responsibility | Already claimed, offline, unauthorized, stale outcomes explicit. Evidence: concurrent authorization/API and Workbench journey. Non-goal: no hidden escalation. |
| P13.3 | P13.2 assignment and revision contract | Connect conflict response, requeue, approved cowork, and transfer request boundaries | Responsibility history and explicit concurrency result | Lost update, expiry, unauthorized transfer rejected. Evidence: concurrent API/authorization scenarios. Non-goal: no client-only locking. |
| P14.1 | Backend lifecycle projection and Workbench routes | Map processing, waiting-user/material/third-party states to queue, card fields, counts, and navigation | Staff can locate every active lifecycle category | Empty/loading/unavailable/stale projections visible. Evidence: route and API projection. Non-goal: no state definition/client sorting. |
| P14.2 | Terminal states and Workbench navigation | Add completed and abandoned/closed queue routes, list/detail return, and permitted reopen boundary | Terminal Claims leave active queues without disappearing | Missing Claim, stale terminal state, unauthorized reopen explicit. Evidence: browser/API state journey. Non-goal: no local terminal emulation. |
| P14.3 | Queue/detail error envelopes and status tokens | Implement loading, empty, unavailable, conflict, and action-failure states with recovery | Staff distinguish no data from failed or stale data | Retry never duplicates mutation; stale content marked. Evidence: browser/API failure paths. Non-goal: no fabricated fallback data. |
| P14.4 | P14.1 route/state matrix and backend state list | Close remaining processing/waiting route, count, filter, and return gaps | Every supported active state has one discoverable entry | Unknown state is explicit unavailable category. Evidence: matrix and browser coverage. Non-goal: no new backend enum. |
| P14.5 | P14.2/P14.3 terminal projections | Close completed/abandoned return links, counts, status cues, and detail transitions | Terminal detail returns to correct queue with context | Deleted/inaccessible Claim explicit. Evidence: route coverage. Non-goal: no client terminal inference. |
| P15.1 | Claim projection, handoff, fields, Evidence, tags, RAG, policy, history, third-party, permissions | Define staff context/action matrix: summary, expansion, editability, actions, hidden, unavailable | Shared Workbench components have a single information hierarchy | Source/time/confidence/unavailable remain visible. Evidence: matrix mapped to API fields/routes. Non-goal: no unapproved backend fields. |
| P15.2 | Claim-linked sessions, staff auth, message API, handoff state | Connect conversation entry to Claim tab; enforce recipient/visibility, send, draft, and revision boundaries | Staff sends in the correct Claim-linked session | Unauthorized recipient, stale revision, offline, duplicate explicit. Evidence: browser/API session journey. Non-goal: no orphan conversation list. |
| P15.3 | Staff permissions, Runtime actions, P3/P5, Claim projection | Wire allowed actions, field edits, third-party requests, and next-state mutation with confirmation/audit | Staff action updates authoritative state and claimant projection | Unauthorized, conflict, invalid transition, unavailable, unknown explicit. Evidence: auth/integration/browser. Non-goal: no direct DB mutation. |
| P16.1 | Staff Agent session, action registry, permissions, message/note/request contracts | Define draft types, target audience, required confirmation, editable fields, and audit metadata | Candidate action contract for Runtime | Unsupported draft, missing target, permission mismatch rejected before execution. Evidence: draft-to-action examples. Non-goal: no implicit execution. |
| P16.2 | P16.1 and Runtime execution/authorization | Connect confirmation, idempotent execution, result/audit persistence, Claim and claimant/Workbench projections | Confirmed draft yields one explicit business result | Denied, stale, timeout, unavailable, unknown visible. Evidence: auth/integration journey. Non-goal: no Agent bypass. |
| P17.1 | Claim/session persistence, retention, incomplete projection | Persist incomplete marker, last meaningful interaction, recovery context, and follow-up task | Claimant and Workbench find incomplete Claim through APIs | Anonymous retention and missing session explicit. Evidence: API persistence/recovery. Non-goal: no duplicate Claim. |
| P17.2 | P17.1, thresholds, permissions, notification/action contracts | Implement follow-up, recovery, staff abandonment, and threshold transitions | Lifecycle state and next action project consistently | No response, repeated follow-up, refusal, expired recovery explicit. Evidence: lifecycle API/browser. Non-goal: no early deletion. |
| P17.3 | Retention policy, access rules, audit, projections | Execute purge/anonymisation, deny old-session access, preserve required audit, update projections | Expired incomplete Claim is no longer recoverable through old credentials | Partial purge/storage/audit failure explicit and retryable. Evidence: auth/persistence/lifecycle tests. Non-goal: no silent deletion. |
| P18.1 | Current Control Plane PR, config models, runtime profile, audit contract | Complete revision/validation/publish/rollback/audit boundary in the existing path | Admin can move configuration through governed lifecycle | Invalid, stale, publish, rollback failures visible. Evidence: API and browser journey. Non-goal: no CI or parallel management path. |
| P18.2 | P4/P6/P11 outputs and Control Plane config contract | Add governed knowledge, model, Agent-rule, and integration records with validation, version, owner, publish scope | Admin can inspect/change these inputs through lifecycle | Invalid rule or unavailable provider remains unpublished. Evidence: API/config journey. Non-goal: no live-provider claim. |
| P18.3 | Identity, runtime, evaluation, health contracts | Add account, runtime-profile, evaluation, and runtime-status views/actions | Control Plane presents authoritative operational state | Denial, stale revision, unavailable runtime explicit. Evidence: authorization/browser. Non-goal: no shared claimant/staff credentials. |
| P18.4 | Failure records, readiness, sprint outcomes | Record unresolved configuration, unavailable capabilities, evidence gaps, owner, status, and next action | Durable operational backlog with honest status | Unknown never becomes success. Evidence: Control Plane readback. Non-goal: no hidden feature implementation. |
