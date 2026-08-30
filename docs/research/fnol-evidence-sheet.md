# FNOL Evidence Sheet

## 1. Purpose and Scope

This evidence sheet consolidates the research supporting claimant and employee needs in the first-notice-of-loss (FNOL) journey. It separates direct survey findings, official or published evidence, qualitative signals, and hypotheses so that each conclusion can be used within its evidential limits.

The claimant section audits the existing exploratory survey without changing its responses or reported data. The employee section combines published operational evidence with one consented insurance-industry interview, while a separate five-participant website observation provides exploratory claimant-side evidence. No internal workflow telemetry or direct observation of employees performing claims work was available. The qualitative findings therefore remain bounded to what participants stated or did and are not treated as industry-wide prevalence, measured handling time, or target-system usability.

## 2. Evidence Standard

| Status | Meaning | Appropriate use |
|---|---|---|
| **Source linked** | A traceable public source supports the stated finding. | Use with the stated scope and limitation. |
| **Survey documented** | A reported survey result is mathematically consistent with its numerator and denominator. | Use as an exploratory signal, not a population estimate. |
| **Interview documented** | A consented participant statement is traceable to the repository interview notes. | Use as bounded qualitative evidence; do not generalise from one participant. |
| **Observation documented** | A consented exploratory observation is traceable to the repository observation notes. | Use as a usability signal within the observed task and sample only. |
| **Partial** | The finding is relevant but its original source metadata or direct evidence is incomplete. | Use only as a qualitative theme and identify the missing validation. |
| **Hypothesis** | The statement is plausible but has not been established for the named organisation or workflow. | Validate before presenting it as a finding. |

Evidence status indicates traceability, not universal validity. Official evidence may still be event-specific, company-specific, or descriptive rather than causal.

## 3. Quality-Control Summary

- Survey source: [`claimant-survey-final-responses.csv`](./claimant-survey-final-responses.csv), exported from the final Google Forms response set and checked 13 August 2026. The owner-controlled [Google Sheets response source](https://docs.google.com/spreadsheets/d/1QVGBnV9EiZ_2JnnEHMKe2xCEuP7JLrA4KS1Vwr2KYBE/edit?gid=1673612912#gid=1673612912) remains the collection record.
- Questionnaire wording source: [`insurance-claim-customer-experience-survey.pdf`](./insurance-claim-customer-experience-survey.pdf), an eight-page export of the Google Form stored in this research folder.
- The final export contains **156 submissions**. One respondent selected “No, I do not wish to participate” and was excluded before analysis, leaving **155 consented respondents**.
- Blank answers are retained as missing data, not classified as incorrect responses. Each result uses the number who answered that question: overall questions `n=155`, previous-claim questions `n=48`, priority and human-support questions `n=60`, hypothetical-incident questions `n=12`, and the open-text improvement question `n=144`.
- All reported survey percentages were recalculated from their stated counts and question-specific denominators. For multi-select questions, one respondent contributes at most once to each option or combined concept even if the export repeats a label.
- The previous-claim subgroup contains 48 respondents. Its results are retained as sample findings and are not treated as population prevalence.
- Multi-select results are not expected to total 100%.
- Counts were recalculated directly from the linked response sheet. Each metric below retains its numerator, denominator and question context.
- The response sheet remains access-controlled by its owner even though link-view access is currently enabled. Do not copy free-text responses into public research artifacts without an additional privacy review.
- Interview and observation source: [`Insurance Industry Interview and Supporting User Observation`](./insurance-industry-interview-and-user-observation.md), recorded 11 August 2026. The notes document consent, participant role, method, evidence IDs and research limitations without including the participant's name, employer or customer data.

## 4. Claimant Evidence

### 4.1 Exploratory Survey Register

| ID | Finding | Exact result | Scope | Research relevance | Boundary | Status |
|---|---|---:|---|---|---|---|
| S01 | Most respondents had no previous claim experience. | 69.0% (107/155) | All consented respondents | Users without prior claim experience need orientation that does not assume process knowledge. | Exploratory, self-reported sample; not a population estimate. | Survey documented |
| S02 | A substantial minority had previous claim experience. | 31.0% (48/155) | All consented respondents | Prior experience does not remove the need for an efficient repeat-claim path. | Exploratory, self-reported sample; not a population estimate. | Survey documented |
| S03 | Moderate confidence was the most common rating for understanding policies and the claim process. | 52.3% selected 3/5 (81/155) | All consented respondents | Use plain language and explain the process in context. | Self-reported confidence, not observed knowledge. | Survey documented |
| S04 | Progress or next-stage visibility was the leading combined priority. | 71.7% (43/60) | Respondents who answered the priority item; multi-select | Show status, ownership, next step and expected timing. | Combined concept covers transparent updates, progress tracking, what happens next and stage expectations; question-specific denominator. | Survey documented |
| S05 | Simple documentation or easy evidence upload was also a leading priority. | 48.3% (29/60) | Respondents who answered the priority item; multi-select | Provide claim-specific evidence guidance and a visible completeness view. | Combined concept; question-specific denominator. | Survey documented |
| S06 | Respondents were concerned that AI might misunderstand the incident. | 41.9% (65/155) | All consented respondents; multi-select | Let users review and correct information structured by AI. | Combined equivalent wording; measures concern, not system performance. | Survey documented |
| S07 | Respondents were concerned that AI might not handle a complex or unusual case. | 45.8% (71/155) | All consented respondents; multi-select | Complex or exceptional cases require a clear route to human judgement. | Combined equivalent wording; exploratory preference. | Survey documented |
| S08 | Respondents were concerned about AI making decisions that should remain controlled. | 45.8% (71/155) | All consented respondents; multi-select | Keep deterministic or human authority for consequential claim decisions. | Combined equivalent wording; does not establish legal or operational decision boundaries. | Survey documented |
| S09 | Immediate-action guidance led the hypothetical-incident responses. | 75.0% (9/12) | Respondents who answered the hypothetical minor-vehicle item | Provide bounded immediate-action guidance before full intake. | Question-specific small subgroup; blanks are not treated as negative responses. | Survey documented |
| S10 | Guidance on photos and evidence was also prominent in the hypothetical item. | 66.7% (8/12) | Respondents who answered the hypothetical minor-vehicle item | Give evidence prompts appropriate to the incident. | Question-specific small subgroup. | Survey documented |
| S11 | Previous claimants reported unclear reporting requirements. | 35.4% (17/48) | Previous-claim respondents | Ask only relevant questions and show what information is required. | Combined equivalent wording; sample finding, not population prevalence. | Survey documented |
| S12 | Previous claimants most often reported not knowing claim status after submission. | 60.4% (29/48) | Previous-claim respondents | Make status, ownership and timing visible without requiring claimant follow-up. | Combined equivalent wording; sample finding, not population prevalence. | Survey documented |
| S13 | Human support was preferred when information or policy terms were unclear. | 43.3% (26/60) | Respondents who answered the human-support item; multi-select | Keep an accessible human-support path when comprehension is insufficient. | Combined equivalent wording; question-specific denominator. | Survey documented |
| S14 | Human support was preferred for urgent or stressful situations. | 41.7% (25/60) | Respondents who answered the human-support item; multi-select | Urgency and distress remain explicit escalation signals. | Combined equivalent wording; preference does not define a service level. | Survey documented |

### 4.2 Survey Calculation Checks

| ID | Calculation | Recalculated value | Reported value | Result |
|---|---:|---:|---:|---|
| S01 | 107 / 155 | 69.0% | 69.0% | Match |
| S02 | 48 / 155 | 31.0% | 31.0% | Match |
| S03 | 81 / 155 | 52.3% | 52.3% | Match |
| S04 | 43 / 60 | 71.7% | 71.7% | Match |
| S05 | 29 / 60 | 48.3% | 48.3% | Match |
| S06 | 65 / 155 | 41.9% | 41.9% | Match |
| S07 | 71 / 155 | 45.8% | 45.8% | Match |
| S08 | 71 / 155 | 45.8% | 45.8% | Match |
| S09 | 9 / 12 | 75.0% | 75.0% | Match |
| S10 | 8 / 12 | 66.7% | 66.7% | Match |
| S11 | 17 / 48 | 35.4% | 35.4% | Match |
| S12 | 29 / 48 | 60.4% | 60.4% | Match |
| S13 | 26 / 60 | 43.3% | 43.3% | Match |
| S14 | 25 / 60 | 41.7% | 41.7% | Match |

The current AI-comfort distribution is rating 1 = 9, rating 2 = 11, rating 3 = 58, rating 4 = 66, and rating 5 = 11 (`n=155`), producing a weighted average of **3.38/5**. This supports an assisted, user-correctable experience with an available human path; it does not support autonomous high-impact decisions.

### 4.3 Published and Public Claimant Evidence

| ID | Source and finding | Evidence or scope | Primary relevance | Boundary | Status |
|---|---|---|---|---|---|
| C01 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/): claim confirmations did not consistently explain progress updates. | Only 43% of the seven surveyed insurers included how updates would be provided. | Progress, timing and ownership visibility. | Seven-insurer weather-event review; not routine-claim prevalence. | Source linked |
| C02 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/): information requests should be consolidated and systems should retain information from internal and external sources. | Regulatory recommendation following the 2023 North Island weather events. | Tell-us-once continuity and reduced repetition. | Recommendation, not a measured frequency. | Source linked |
| C03 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/): consumers had difficulty with exclusions, cover limits, gradual damage, pre-existing damage and betterment. | Findings from weather-event claims, brokers and dispute-resolution schemes. | Plain-language coverage and evidence explanations. | Event-specific research. | Source linked |
| C04 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/): speed of claim progress was a material complaint theme. | 43% of complaints in one insurer's North Island weather-event analysis concerned speed. | Explain delays and revised timeframes. | One insurer and one event context. | Source linked |
| C05 | [Salesforce — Customer Expectations](https://www.salesforce.com/small-business/what-are-customer-expectations/): customers report repeating or re-explaining information. | Reported figure: 56%. | Preserve information across representatives and channels. | Secondary company research summary; methodology should be checked before formal statistical use. | Source linked |
| C06 | [Genesys — State of Customer Experience](https://www.genesys.com/resources/state-of-cx): retained context is important when customers switch channels. | Reported figure: 95%. | Context-rich human handoff. | Vendor research; sample and methodology require confirmation for formal statistical use. | Source linked |
| C07 | [Microsoft Learn — Bot-to-human handoff](https://learn.microsoft.com/en-us/azure/bot-service/bot-service-design-pattern-handoff-human?view=azure-bot-service-4.0): context and transcript can accompany a transfer. | Official technical design guidance. | Demonstrates a feasible context-preserving handoff pattern. | Design evidence, not proof that an insurer implements it. | Source linked |
| C08 | [McKinsey — Superior customer experience in insurance](https://www.mckinsey.com/industries/financial-services/our-insights/the-growth-engine-superior-customer-experience-in-insurance): customers experience touchpoints as one journey. | High-level insurance customer-experience research. | Continuous claim context across channels. | Framing evidence, not FNOL implementation evidence. | Source linked |
| C09 | [Reddit — State claim communication example](https://www.reddit.com/r/newzealand/comments/12i6icr/any_advice_on_how_to_get_a_reply_from_state/): one claimant described repeated requests and limited response after online submission. | One self-selected public account. | Qualitative illustration of repetition and update problems. | Not independently verified; cannot establish frequency. | Source linked |
| C10 | [Trustpilot — State Insurance reviews, page 7](https://www.trustpilot.com/review/state.co.nz?page=7): reviews include contact difficulty, inconsistent information and repeated explanations. | Self-selected public reviews. | Qualitative themes of continuity, ownership and updates. | Selection bias; cannot establish prevalence. | Source linked |
| C11 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/): insurers should improve identification and treatment of consumers in vulnerable circumstances. | Regulatory finding and recommendation. | Detect vulnerability and provide suitable human support. | Weather-event context. | Source linked |
| C12 | [The Guardian — DPD chatbot incident](https://www.theguardian.com/technology/2024/jan/20/dpd-ai-chatbot-swears-calls-itself-useless-and-criticises-firm): an automation failure required staff intervention. | Public reporting about logistics customer service. | Illustrates why an effective human path is necessary. | Non-insurance case; does not prove context loss. | Source linked |
| C13 | [CX Dive — Klarna human-service investment](https://www.customerexperiencedive.com/news/klarna-reinvests-human-talent-customer-service-AI-chatbot/747586/): high automation does not remove the need for service quality and human choice. | Public reporting about fintech customer service. | Human capability and automation boundaries. | Does not disclose individual handoff payloads. | Source linked |
| C14 | [INNOQ — AXA chatbot case](https://www.innoq.com/en/cases/axa-chatbot-als-unterstuetzung-im-kundenservice/): unresolved enquiries can be routed to a human department. | Insurance case study. | Evidence of a visible human route. | Does not establish transcript, field or attachment transfer. | Source linked |
| C15 | [Insurance Business — AA Ireland chatbot case](https://www.insurancebusinessmag.com/us/news/technology/how-chatbots-are-revolutionizing-the-insurance-customers-journey-194615.aspx): bot and human chat can form one service chain. | Insurance and roadside-service case. | Same-chain bot-to-human transfer. | Not FNOL proof; structured claim-context transfer is not established. | Source linked |
| C16 | [Microsoft Customer Story — Zurich Hong Kong](https://www.microsoft.com/en/customers/story/24082-zurich-dynamics-365-contact-center): staff can access conversation history, policy and prior-contact information in a unified environment. | Vendor customer story involving insurance service and motor claims. | Positive comparator for context-rich service. | Full FNOL fields and attachment transfer are not disclosed. | Source linked |
| C17 | [KLM — Human and AI conversations](https://news.klm.com/klms-next-step-using-artificial-intelligence-on-social-media/): AI and staff can operate in the same cross-channel conversation. | Aviation company statement. | Same-conversation human takeover pattern. | Non-insurance; no structured FNOL-field evidence. | Source linked |
| C18 | [Vodafone — AI and human agents](https://www.linkedin.com/posts/vodafone_asktheexperts-customerconnections-vodafone-activity-7465376975310954496-JoRu): customer context and history can support continuation by staff. | Telecommunications company account. | Context-continuity design principle. | Non-insurance and not independently audited. | Source linked |
| C19 | [State — Contact](https://www.state.co.nz/contact): digital and contact channels are publicly available. | Public channel information. | Channel choice. | Does not reveal the handoff payload or internal workflow. | Source linked |
| C20 | [Tower — Contact](https://www.tower.co.nz/contact-us/): My Tower, online and phone channels are publicly available. | Public channel information. | Channel choice. | Does not reveal continuity between channels. | Source linked |
| C21 | [NZI — Claims](https://www.nzi.co.nz/claims): NZI primarily works through brokers and also publishes direct contact information. | Public channel information. | Broker and specialist routing. | Does not establish context transfer. | Source linked |
| C22 | [Westpac — Vehicle insurance claims](https://www.westpac.co.nz/insurance/car-vehicle/make-a-claim-on-car-vehicle-insurance/): online and emergency-phone pathways are available. | Public channel information. | Digital and urgent-support pathways. | Does not reveal internal workflow or continuity. | Source linked |

### 4.4 Exploratory Claimant Observation Evidence

| ID | Direct evidence | Interpretation | Strength | Limitation | Status |
|---|---|---|---|---|---|
| OBS-01 | During the consented AA Insurance website exercise, 5/5 participants expressed a desire to abandon when they encountered unfamiliar information such as a policy number. | Unfamiliar terminology or prerequisites may create an abandonment point. | Direct exploratory task observation. | Five participants; one insurer website; not representative of all claimants or FNOL systems. | Observation documented |
| OBS-02 | Available Help did not sufficiently resolve the immediate issue for the observed participants. | Contextual, in-flow guidance may be more useful than generic help or redirection. | Direct exploratory task observation. | Help interactions were not measured as a controlled usability comparison. | Observation documented |
| OBS-03 | 5/5 participants described the process as too troublesome to continue. | Process friction may discourage completion. | Direct exploratory task observation. | Small convenience sample; does not establish an abandonment rate. | Observation documented |
| OBS-04 | 2/5 participants would consider calling, while 3/5 did not want to call. | A telephone-only escalation route may not suit every user. | Direct exploratory task observation. | Preference in one exercise; no demographic or channel-preference study was conducted. | Observation documented |
| OBS-05 | Some participants appeared uncomfortable with phone communication. | Text-based support may be useful for some users. | Informal researcher observation. | Not formally measured; remains provisional. | Observation documented |

**Original source:** [`Insurance Industry Interview and Supporting User Observation`](./insurance-industry-interview-and-user-observation.md), sections 6–10. The source records consent and keeps the website observation separate from the industry interview.

### 4.5 Claimant Findings Requiring Further Validation

| ID | Finding | Current evidence | Required validation | Status |
|---|---|---|---|---|
| Q01 | Seven supplied customer statements support themes of opaque decisions, repeated requests, delays, absent updates and low settlement concerns. | The statements are available, but their original URLs, platforms and dates were not supplied. | Add source URL, platform, date and insurer for each statement before using them as traceable external evidence. | Partial |
| H01 | A named insurer may lose context during an automated-to-human handoff. | Industry guidance and comparator cases establish the risk and technical design options, but not its presence at State, Tower, NZI or Westpac. | Test each journey directly or interview staff and claimants before attributing the problem to an insurer. | Hypothesis |

## 5. Employee Evidence

### 5.1 Research Boundary

The employee evidence below supports two professional user groups: **Claims Professionals**, who assess completeness, investigate exceptions and progress individual claims; and **Claims Operations Leads**, who manage queues, capacity, prioritisation, quality and service performance.

The sources establish information complexity, surge conditions, third-party coordination, specialist-resource constraints and the need for administrative support. One consented insurance-industry auditor interview adds direct qualitative evidence about repeated customer explanations and their effect on employee time. It does **not** directly measure employee satisfaction, handling time, error rates or interface usability. Statements about frustration, workload experienced by a particular team, or defects in a current internal system remain unverified until broader staff research or operational data is available.

### 5.2 Employee Evidence Register

| ID | Source and finding | Employee users | Operational implication | Boundary | Status |
|---|---|---|---|---|---|
| W01 | [AA Insurance — Reporting a claim online](https://www.aainsurance.co.nz/help/article/360020406712-How-can-I-report-a-claim-online) lists policy, identity, incident, date, involved-person, witness, emergency-service and third-party information, with additional fields varying by product. | Claims Professional | Intake must identify the applicable facts and distinguish required from conditional information. | Published customer requirements demonstrate information complexity, not staff effort or system usability. | Source linked |
| W02 | [Tower — Claims](https://www.tower.co.nz/claims/) publishes different supporting-evidence sets for vehicle, contents, property, business, travel and pet claims, including photos, receipts, police records, reports, invoices, income evidence and veterinary documents. | Claims Professional | Completeness checking and evidence prompts need to vary by claim type and circumstance. | Public requirements do not reveal Tower's internal handling workflow. | Source linked |
| W03 | [Tower — Claims](https://www.tower.co.nz/claims/) states that claims may be assigned to a claims manager, repair or supply partner, or assessor depending on the case. | Claims Professional; Claims Operations Lead | Ownership, requested action and context must remain clear when work moves between internal and external participants. | Establishes participant involvement, not that a handoff currently fails. | Source linked |
| W04 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) reports 118,000 claims and close to NZ$4 billion of insured-property damage from the 2023 North Island weather events, describing an unprecedented surge and many highly complex claims. | Claims Operations Lead; Claims Professional | Queueing, triage and capacity must cope with sharp event-driven variation in volume and complexity. | Catastrophe conditions are not representative of business-as-usual volume. | Source linked |
| W05 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) reports staff redeployment, dedicated event teams, offshore contingency resources and, for one insurer, 300 additional staff. | Claims Operations Lead | Surge response requires visible workload, skills, ownership and prioritisation across temporary or redistributed capacity. | Describes a multi-insurer event review; it does not quantify effort in this project's target organisation. | Source linked |
| W06 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) recommends reducing administrative burden and using technology so trained staff can be allocated across event and business-as-usual claims. | Claims Operations Lead; Claims Professional | Structured intake and automation should reduce administration while preserving expert judgement for complex work. | Regulatory recommendation, not proof that a proposed tool will deliver the benefit. | Source linked |
| W07 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) states that claimants may receive requests from multiple insurer staff and third parties and recommends systems that capture and manage information from internal and external sources. | Claims Professional | Staff need a shared evidence state showing what is received, missing, conflicting, pending and requested. | Event-based finding; the extent of repetition in routine FNOL is not quantified. | Source linked |
| W08 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) found that insurers did not always directly oversee outsourced claim activity and recommends adequate oversight of all third parties, including repairers. | Claims Operations Lead; Claims Professional | Multi-party claims require visible ownership, status, authority and traceable actions. | Does not prove that every insurer or claim has an oversight failure. | Source linked |
| W09 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) reports shortages in loss assessment, valuation and geotechnical expertise during the event response. | Claims Operations Lead | Scarce specialist capacity increases the importance of prioritisation and complete referral packages. | Catastrophe-specific resource pressure. | Source linked |
| W10 | [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/) says staff need training and adaptable systems to identify and appropriately support consumers in vulnerable circumstances. | Claims Professional; Claims Operations Lead | Vulnerability indicators must be visible and routed to appropriately trained staff without replacing human judgement. | Regulatory expectation; the source does not define a complete automated detection method. | Source linked |
| W11 | [Tower — 2026 shareholder-meeting update](https://www.nzx.com/announcements/467670) reports that 53% of New Zealand motor claims progressed straight through to repairers and 74% were completed through Tower's preferred repair-partner network. | Claims Operations Lead; Claims Professional | Automation and partner networks can coexist; staff views need to distinguish straight-through work, exceptions and externally progressing claims. | Company-reported motor-claim figures at a point in time; not an independent usability study. | Source linked |

### 5.3 Interview Evidence Register

| ID | Direct evidence | Interpretation | Strength | Limitation | Status |
|---|---|---|---|---|---|
| INT-01 | The insurance-industry participant stated that customers may not understand what they need to prepare or do themselves. | Intake guidance and responsibility clarity may be insufficient for some customers. | Direct statement from a consented insurance-industry participant. | One auditor interview; not a prevalence measure and not representative of all claims roles or organisations. | Interview documented |
| INT-02 | The participant stated that customers may continue asking staff to handle tasks the customer must complete themselves. | Repeated procedural explanation may create avoidable staff workload. | Direct statement from a consented insurance-industry participant. | No frequency, duration or handling-time measurement was collected. | Interview documented |
| INT-03 | The participant stated that repeated customer explanation consumes employee time. | Better pre-intake guidance may reduce procedural workload while preserving staff support. | Direct statement from a consented insurance-industry participant. | Causal impact of any proposed design was not tested. | Interview documented |

**Original source:** [`Insurance Industry Interview and Supporting User Observation`](./insurance-industry-interview-and-user-observation.md), sections 2–5 and 9–12. Handoff was not discussed, so no handoff finding is inferred from this interview.

### 5.4 Evidence-Based Employee Pain Points

#### E1. Information-intensive and claim-specific intake

Claims Professionals must turn a claimant's event narrative into the correct policy, incident, participant and evidence fields. Published insurer requirements show that the required information changes materially by claim type. A professional workflow therefore needs conditional intake, provenance, confidence and completeness information rather than one undifferentiated narrative or static checklist.

**Evidence base:** W01, W02, W07, INT-01, INT-02.
**Validation still needed:** direct handling-time data, common missing fields, re-contact rates, error patterns and broader staff usability research.

#### E2. High and event-driven workload pressure

Claims Operations must manage claims that differ in urgency, completeness, complexity and required expertise. The FMA evidence shows that major events can create abrupt demand, staff redeployment and specialist shortages while business-as-usual claims continue. Operations users therefore need reliable state, ownership and prioritisation information rather than arrival order alone.

**Evidence base:** W04, W05, W06, W09, W11, INT-03.
**Validation still needed:** target-team queue volumes, service levels, staffing model, prioritisation rules and the actual causes of delay.

#### E3. Multi-party evidence and handoff coordination

Claims commonly involve staff, repairers, assessors and specialists. Progress depends on transferring confirmed facts, outstanding evidence, ownership, authority and the requested next action. Published evidence establishes the coordination requirement and the risk of fragmented requests, but a specific handoff failure must not be claimed without direct testing.

**Evidence base:** W03, W07, W08, W11.  
**Validation still needed:** internal workflow maps, role permissions, partner interfaces, handoff samples, duplicate-request frequency and interviews with claims-handling and operations roles. The existing auditor interview did not discuss handoff.

#### E4. Applying judgement safely under incomplete or sensitive information

Employees must distinguish routine processing from claims involving vulnerability, ambiguity, conflict, scarce expertise or consequential decisions. Automation may organise and surface information, but the evidence supports maintaining trained human ownership for exceptions and sensitive cases.

**Evidence base:** W06, W09, W10.  
**Validation still needed:** approved escalation criteria, authority limits, quality controls, audit requirements and false-positive/false-negative impacts.

### 5.5 Employee Research Priorities

The next research cycle should validate the evidence-informed findings with:

1. semi-structured interviews with Claims Professionals and Claims Operations Leads;
2. observation of routine, incomplete, complex and surge FNOL cases;
3. workflow data covering queue age, re-contact, missing information, reassignment and time to first meaningful action;
4. samples of internal-to-internal and internal-to-partner handoffs;
5. role and permission testing for claim access, updates and consequential decisions; and
6. usability testing of the employee claim view using realistic exceptions and conflicting evidence.

## 6. Cross-Role Synthesis

| Shared need | Claimant perspective | Employee perspective | Evidence boundary |
|---|---|---|---|
| Clear information requirements | Know what to provide now and what can follow later. | See claim-specific completeness and provenance. | Strongly supported as a need; target-system performance is untested. |
| One continuous claim context | Avoid repeating the story and resending evidence. | Avoid reconstructing facts and duplicate requests. | Industry and regulatory support; named-insurer continuity requires direct testing. |
| Visible progress and ownership | Understand status, next step and timing. | Manage queues, responsibility, service timing and exceptions. | Strong in weather-event findings; routine prevalence is not quantified. |
| Safe human involvement | Reach a person for urgent, stressful or complex situations. | Apply professional judgement to ambiguity, vulnerability and high-impact decisions. | Survey preference and regulatory guidance support the need; service model remains to be defined. |
| Traceable evidence and decisions | Understand why information is requested and how outcomes relate to facts. | Distinguish sources, gaps, conflicts, actions and authority. | Operational requirement is well supported; internal control design needs validation. |

## 7. Overall Limitations

- The claimant survey is exploratory and self-selected; it informs priorities and personas rather than population estimates.
- Question-level response counts vary. Blank answers are retained as missing data, and every percentage must preserve its question-specific denominator.
- The previous-claim branch contains `n=48`; priority and human-support items contain `n=60`; the hypothetical minor-vehicle item contains `n=12`.
- Public reviews are self-selected and cannot establish issue frequency.
- Some industry statistics come from vendor or company material and require methodology checks before formal statistical use.
- Weather-event research provides strong evidence of surge and coordination conditions but should not be generalised automatically to every routine claim.
- Employee findings combine published process and operational evidence with one consented insurance-industry auditor interview; they do not constitute representative staff research.
- Published requirements and multi-party processes establish work conditions; they do not by themselves prove employee frustration, excessive handling time or defects in a particular internal system.
- Competitor channel availability does not prove context continuity. Direct journey testing is required before making named-insurer comparisons.

## 8. Evidence Register Maintenance

For each new item, record:

- a unique evidence ID;
- the user side: claimant, employee or cross-role;
- source type and title;
- the precise claim or metric supported;
- source URL and section where available;
- sample or operational scope;
- the relevant pain point or professional need;
- the evidence boundary;
- verification status and checked date; and
- the next validation action.

The final anonymous survey export is stored as [`claimant-survey-final-responses.csv`](./claimant-survey-final-responses.csv), with the collection record retained in the linked owner-controlled Google Sheet. The consented, anonymised interview and observation record is stored in this repository as [`Insurance Industry Interview and Supporting User Observation`](./insurance-industry-interview-and-user-observation.md). Any future raw notes or internal workflow evidence should be stored with suitable consent, privacy and access controls. Derived percentages must retain their numerator, question-specific denominator and question wording.
