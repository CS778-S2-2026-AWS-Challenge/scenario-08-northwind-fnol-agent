# Sprint 2 第二周计划：在现有实现上完成 MVP

## 范围

- **周期：** 2026 年 8 月 24 日至 28 日
- **阶段：** Sprint 2 第二周
- **里程碑：** MVP Presentation
- **目标：** 把本周确认的产品、数据和接口边界落实到现有代码，继续并行开发双端、Agent、API、数据库、知识库和证据能力，形成一套可持久化、可重复验证的 MVP

## Sprint 2 主张

用两周把 Sprint 1 的全路径 prototype 推进为可重复运行的 MVP：团队继续按栈
并行开发，在现有代码上修正客户交互和 Agent 行为，建立可切换的数据运行配置、
通配模型 API 和首版知识库，并跑通从自然报案到 claim 推进或人员接管的共享状态。

## 责任延续

Week 4 不重新分配技术栈：

- `Ysoseri1224`：Claimant frontend + Agent behaviour，继续负责自然交互、Agent orchestration、模型 API gateway 和 claimant 路径；
- `liyang6620`：Backend API + AWS integration，继续负责 API、互斥 data runtime profile 的装配、Cloudflare/AWS adapter 和部署入口；
- `jxu316-arch`：Persistence/session + policy/history data，继续负责逻辑数据模型、MongoDB profile、session、Claim State 和结构化 policy/history 查询；
- `LLL263`：Staff workbench + handoff/write-back，继续负责 staff review、ownership、handoff、协同任务和 claimant-safe 写回；
- `bdfa123`：Evidence/media lifecycle + fixture infrastructure，继续负责 evidence ingestion、文件处理、知识库 ingestion fixture 和跨路径验证工具。

每个人继续修复自己栈内的问题，并参与其他成员负责路径的交叉验收。

## Week 4 起点

产品、数据和接口方向在 Week 3 结束前完成修订，因此 Week 4 不再设置“对齐方向”
任务，也不从零重建系统。所有成员从最新主分支和修订后的契约出发，先删除或修改
与新主张冲突的旧实现，再在原有可用能力上继续开发。

Week 4 需要完成：

1. 把“客户自然描述、系统内部结构化、必要时才确认”的 Agent 行为落实到现有代码；
2. 建立官方 API、中转站、自定义接口和本地接口均可扩展的模型 gateway，完成候选模型的基础比较；
3. 明确数据分类和逻辑 schema，建立 Cloudflare、MongoDB、AWS 三套互斥 profile 的共同接口，并至少跑通一套真实持久化配置；
4. 建立云端知识来源到解析、切分、索引、引用和评估的首版 RAG 流程；
5. 继续连接 claimant、Agent、API/data、staff 和 evidence 的共享 Claim State；
6. 执行成功、失败、resume、pending、urgent、knowledge retrieval 和 professional review 场景；
7. 由非实现者交叉验证，修复阻塞 MVP 的问题并记录真实限制。

## Week 4 并行推进内容

| 技术栈 | 第二周目标 |
| --- | --- |
| Claimant frontend | 自然叙述、最少必要确认、材料补充、恢复和人工接管形成连续体验 |
| Agent and model API | Agent 只接收有界上下文；模型提供方可替换；模型输出继续受确定性 authority 检查 |
| Backend API | 旧接口与修订后的产品和数据契约一致；成功、失败、timeout 和 unavailable 行为清楚 |
| Data and runtime profiles | 数据分类和 schema 明确；一个进程只启用 Cloudflare、MongoDB 或 AWS 中的一套 profile；至少一套真实运行 |
| Knowledge base and RAG | 云端知识来源可导入、切分、索引、过滤和引用；错误版本、证据不足和提示注入路径可测试 |
| Staff workbench | staff 能看到结构化上下文、来源、缺口和待决定事项，并把允许的信息写回 claimant |
| Evidence and fixtures | 原始文件、metadata、抽取建议和知识文档分离；核心场景可以重复运行和独立验收 |

## 数据运行配置原则

- Cloudflare、MongoDB 和 AWS 是三套互斥的数据运行配置，不是同一运行实例内的组合服务。
- 一个进程只选择一个 profile；不能因为某项能力缺失而静默读取或写入第二个 provider。
- 三套 adapter 遵守相同的 domain ports、visibility、revision、idempotency 和错误契约。
- 未完成的 profile 在启动时明确报告缺失能力，不把 fixture 结果描述为真实云端结果。
- AWS 和其他云服务只按实际确认的 access、schema、permission 和限制接入。

## 模型选择与训练准备

- 首先验证 API 可用性、结构化输出、工具调用、错误处理、延迟、成本和上下文限制。
- 使用同一批 Agent 场景比较候选模型，不凭单次对话决定模型。
- 整理可授权使用的对话、纠正记录和失败案例，形成后续训练或微调的数据基础。
- 在训练数据规模、授权、标签质量和评估基线明确前，不把 fine-tuning 写成已完成能力。

## 共享质量门

最终检查由多名成员共同完成：

- 实现者先完成本栈检查；
- 相邻栈负责人检查接口和状态变化；
- 非实现者重复运行场景；
- blocker、实际结果、预期结果和复现方式写入 card；
- 只有交付物和验收结果都成立，card 才进入 Done。

`bdfa123` 负责 evidence/media 栈并贡献 fixture 工具，不是唯一 tester，也无权
单独决定整个 MVP 是否通过。

## 建议的五天推进

| 日期 | 重点 |
| --- | --- |
| Day 1 | 修改与新契约冲突的旧代码；建立 runtime profile、模型 gateway、逻辑 schema 和知识 ingestion 的可测试骨架 |
| Day 2 | 跑通至少一套真实数据库配置；完成首批模型 API 比较；把自然对话和最少确认接入 claimant 路径 |
| Day 3 | 接入首批知识文档和带引用检索；连接 staff review、handoff、evidence 和共享 Claim State |
| Day 4 | 完成跨栈连接，测试 provider/model/RAG 失败、resume、urgent、权限和可见性路径并修复 blocker |
| Day 5 | 稳定 MVP 环境，重复运行核心路径，记录实际能力和限制，并完成 MVP Presentation 所需准备 |

## Week 4 完成条件

- 现有代码与修订后的产品、Agent、数据和 API 契约一致；
- 模型 gateway 至少跑通一个真实 API，并保留官方、中转、自定义和本地接口的扩展边界；
- Cloudflare、MongoDB、AWS profile 具有共同契约且互斥，至少一套真实持久化配置可运行；
- 首批知识文档可被管理、导入、检索和引用，RAG 不直接作 coverage、fraud 或 claim 决定；
- claimant、Agent、backend、staff、evidence 和知识检索围绕同一 Claim State 协作；
- staff 能通过结构化上下文接管，不需要重读完整对话；
- customer-visible、shared 和 internal-only 信息保持分离；
- 核心场景由非实现者重复运行并通过；
- MVP 环境、模型和数据限制、恢复方式及未完成 profile 已如实记录。

本文件只描述周级计划。Week 4 的详细 Kanban card 将在 Week 3 结果明确后再
生成。
