# Evidence-Based Analysis of Third-Party Stakeholders in New Zealand FNOL

**Sprint 3 - P3.2 Independent Challenge Review**

- **Issue:** #587
- **Author:** jxu316-arch
- **Date:** 7 September 2026
- **Scope:** Motor, Home and Contents First Notice of Loss in New Zealand
- **Revision:** 2 - challenge log, unresolved questions and implementation handoff added

## Abstract

This report examines third-party involvement in New Zealand First Notice of Loss (FNOL) for motor, home and contents insurance. It reconstructs the problem from the perspective of a real claimant and claims handler: what external information or assistance is needed, when it becomes available, who is responsible for obtaining it, what authority is required, and what Northwind can truthfully claim to have done.

The evidence indicates that FNOL is not primarily a problem of collecting every possible document before a claim can proceed. It is a coordination problem involving incomplete, time-dependent and differently owned information. Police references may exist before full reports; emergency towing or property mitigation may be needed before detailed assessment; engineering and loss-adjuster reports are often created only after notification; and contents claims may depend more on proof-of-ownership evidence than on operational third-party services.

The report therefore argues that Northwind should model external dependencies by timing, responsibility, authority and evidence state rather than treating third parties as interchangeable APIs. The revised P3.2 output also converts the research into a formal challenge log, an unresolved-question register and an implementation-facing service matrix for P3.3.

> **Core finding:** Northwind should optimise for coordination rather than apparent completeness. A strong FNOL Agent must know what is needed now, what can wait, who owns the unresolved work, what authority is required, and whether an external outcome is actually known.

## 1. Introduction: FNOL is a coordination problem

The original third-party research question appears simple: which outside organisations should Northwind connect to? Real insurance practice suggests that this is the wrong starting point.

In 2025, Insurance Council of New Zealand members handled approximately 1.31 million claims and more than 28,000 complaints entered insurers' internal dispute-resolution processes [1]. At catastrophe scale the coordination problem becomes even more visible: the Auckland Anniversary floods and Cyclone Gabrielle generated 118,037 claims with an estimated cost of about NZ$3.8 billion, and settlement progress differed across house, contents, motor and other categories [2].

These figures matter because a claim develops over time. A damaged car may be recovered within hours but assessed later. A home may require urgent temporary repair before an assessor can safely enter. A Police reference may exist before a complete Traffic Crash Report. Specialist engineering evidence may not be generated until well after the initial claim has been lodged.

Therefore the important FNOL question is not whether every possible piece of evidence has been collected. It is whether the insurer has enough reliable Claim Context to take the next safe action while preserving what remains unresolved.

## 2. What the evidence says about real FNOL

**External evidence is asynchronous.** NZ Police provides non-emergency reporting through 105, while a later Traffic Crash Report is a separate information-access process [3-5]. FENZ information requests illustrate the same structural point: authoritative material can arrive well after the FNOL conversation [8].

**Responsibility is role-specific.** Some information comes from the claimant, some from other people involved, some from public authorities, and some from professionals appointed by the insurer. Asking a claimant for an assessor report before an assessor has been appointed transfers insurer-owned work back to the customer.

**Real access modes are diverse.** External work may occur through phone calls, websites, statutory requests, insurer referrals, physical inspections, private portals and B2B systems. Tower's use of Hello Claims and Panel Quote shows that insurer-repairer digital integration can be real, but it does not prove that the same interface is public or available to Northwind [11].

**Authority is not the same as technical capability.** ACC provides a clear example: electronic injury-claim submission exists, but relevant claims are lodged by eligible health providers and patient authorisation remains part of the process [9]. The existence of a system does not create Northwind's authority to use it.

## 3. Motor, Home and Contents have different external structures

### 3.1 Motor: people, mobility and incident evidence

Motor claims have a strong immediate dependence on incident participants and vehicle mobility. A collision can involve another driver, another property owner and witnesses before any professional service is contacted. Police reporting becomes relevant according to the circumstances, and Police evidence itself is staged: a claimant may first make a 105 report, later receive a reference or acknowledgement, and only subsequently request a full Traffic Crash Report if required [3-5].

The implication is that Police evidence should not be a binary complete/incomplete field. A more realistic progression is:

**Police relevant? -> reported? -> reference available? -> further Police evidence pending?**

Vehicle recovery is a different dependency. An undriveable vehicle may require an immediate operational service, while repair assessment may occur later. Repair networks reinforce the distinction: digital referral can be technically realistic, but access is often governed by insurer-provider relationships rather than public availability.

Motor FNOL should therefore prioritise:

**safety -> mobility -> incident participants/evidence -> later repair and assessment**

### 3.2 Home: mitigation before assessment

Home claims differ because damage can continue after the original event. The immediate question may be whether the property is still becoming more damaged or remains unsafe. Emergency mitigation can therefore precede detailed assessment. Depending on the event, the relevant stakeholder may be a plumber, electrician, builder, glazier, roofer, locksmith or restoration contractor.

Only later may the insurer appoint an assessor, engineer, project manager or valuer. Natural-hazard claims make this sequencing especially clear: NHC states that customers normally claim through their private insurer, which manages the NHCover component and remains the central point of contact [6-7].

Home FNOL should therefore distinguish immediate loss mitigation from later loss assessment. One may be necessary to prevent further harm now; the other may legitimately remain unresolved for days or weeks. The evidence also supports a correction to the P3.1 catalogue: current NHCover concerns residential buildings and land, so NHC is relevant to Home natural-hazard claims but should not automatically be treated as a Contents service [6].

### 3.3 Contents: evidence acquisition rather than service dispatch

Contents FNOL is structurally different. For theft, Police may be relevant. For many other contents claims, however, the central problem is proving what the claimant owned and what happened to it. Useful evidence may include receipts, purchase records, serial numbers, photographs, valuations or repair/service-centre information.

Retailers, banks, manufacturers and valuers can therefore be genuine claim stakeholders without becoming Northwind integrations. The likely journey is often:

**claimant retrieves evidence -> claimant uploads evidence**

rather than:

**Northwind calls retailer API**

Contents is the clearest example of why a provider-centred catalogue can distort the real claim journey.

## 4. The most important analytical finding: incompleteness is normal

The strongest conclusion from comparing the three scenarios is that missing information does not have one meaning. The following states require different ownership and Agent behaviour:

| Example | What "missing" actually means | Correct ownership/state |
|---|---|---|
| Police reference not yet generated | External authority has not yet produced it | Pending external generation |
| Witness cannot currently be contacted | Relevant claimant-side information is unavailable | Claimant-actionable but unavailable |
| Assessor report does not exist | Professional has not yet been appointed or completed work | Insurer-owned later work |
| Receipt cannot be found | Evidence is missing but alternatives may exist | Alternative evidence path |

If Northwind represents all four situations as the same red "missing field", the Agent will behave badly. It may repeatedly ask the claimant for information that does not yet exist or for information the claimant is not responsible for producing.

A more useful model asks whether the information is relevant, needed for the next action, already exists, who owns obtaining it, whether the claim can continue without it, and what its current state actually is.

This is where real-world evidence most strongly supports Northwind concepts such as `required_now`, `candidate_now`, `pending_later` and `WorkItem`. The value of the Agent is not that it makes missing information disappear. Its value is that it understands what kind of missing information it is.

## 5. Authority matters more than API availability

The revised P3.1 material is substantially closer to the correct problem because it concentrates on Police, towing, repairers, assessors, FENZ, MetService, NHC and contents evidence sources. The strongest integration constraint, however, is often not whether a digital interface exists but whether Northwind is entitled to use it.

ACC demonstrates this directly: electronic claim submission exists, but provider eligibility restricts who can lodge relevant claims [9]. Police provides another authority pattern: an insurer may be able to act as an authorised agent in some request contexts, but this is an authority relationship, not evidence of unrestricted machine access [5]. NHC presents a third pattern, where private insurers operate within a defined agency framework [6-7].

These concepts should remain separate:

- claimant consent;
- authority to act;
- staff authority;
- provider eligibility;
- provider authentication; and
- technical access.

Generic infrastructure or the existence of a vendor endpoint cannot substitute for insurance authority.

## 6. Evidence must remain evidence, not become a decision

Assessors, repairers, engineers, MetService and AI damage-analysis systems can all produce useful evidence, but none necessarily owns the final insurance decision. MetService can provide weather evidence [10]. An assessor may document damage. A repairer may provide a quote. An engineer may explain a structural condition. An AI tool may classify visible vehicle damage [15].

These outputs can influence professional judgement, but they do not inherently establish claim acceptance, liability, fraud, coverage or final settlement. For an AI-mediated system, this boundary matters because the transition from external evidence to a high-impact conclusion can otherwise occur invisibly inside model reasoning.

Northwind should therefore preserve source, time, scope, limitation and status for external evidence rather than converting an external output directly into a business conclusion.

## 7. P3.2 Independent Challenge Log

This section converts the narrative review into the explicit P3.2 output required by Issue #587. Verdict language is deliberately conservative:

- **Accepted** means supported for the stated role.
- **Accepted with qualification** means the stakeholder/service is valid but the original framing is too broad.
- **Partial** means only part is supported.
- **Disputed** means current evidence contradicts or does not support the proposition.
- **Unresolved** means P3.3 still requires a team decision or further evidence.

| P3.1 proposition | P3.2 verdict | Evidence-supported correction | What remains unresolved | Implication for P3.3 |
|---|---|---|---|---|
| NZ Police | Accepted with qualification | Separate initial reporting, reference/acknowledgement and later full TCR. Police evidence is staged rather than binary. | Exact Northwind authority and operational request path for TCR. | Model separate reporting/evidence states; do not claim unrestricted API access. |
| AA Roadservice / towing | Partial | Generalise to accident recovery. Ordinary roadside-assistance membership does not by itself prove collision-recovery coverage or insurer dispatch. | Whether Northwind has or intends any insurer/B2B recovery arrangement. | Represent vehicle recovery as the business service; keep provider/access status separate. |
| Repairer | Accepted with qualification | Claimant-selected repair and insurer-authorised repair are different authority paths. | Which path the prototype demonstrates and who can appoint/approve. | Preserve appointment source, authority and status. |
| Assessor | Accepted | Professional assessment is real but usually later insurer-owned work, not minimum FNOL input. | Trigger for appointment and what status counts as accepted/in progress/completed. | Create insurer-owned WorkItem; FNOL may continue while report is pending. |
| Tractable | Conditional / unresolved access | Damage-analysis technology is claim-domain relevant; output remains evidence, not a claim decision. | Northwind commercial/API access and permitted data use are unproven in the supplied evidence. | Treat as simulation or candidate capability unless access is separately evidenced. |
| FENZ | Accepted | Useful especially for asynchronous fire/emergency evidence; request lifecycle can exceed FNOL. | Who should request information in the prototype and under what authority. | Model as pending external evidence, not a synchronous completion requirement. |
| MetService | Accepted | Authoritative weather evidence can support event verification. | Which product/service form Northwind would actually use. | Evidence retrieval only; do not infer coverage from weather evidence. |
| NHC - Home | Accepted with qualification | Natural-hazard handling is normally insurer-mediated; private insurer remains central point of contact. | Exact action/state Northwind should expose in prototype. | Home only; insurer-owned process. |
| NHC - Contents | Disputed | Current NHCover scope in the supplied report supports residential buildings/land rather than a generic Contents service. | Whether any indirect contents relevance should be recorded separately. | Do not model NHC as a normal Contents service without new evidence. |
| Retailer / service centre / valuer | Accepted as evidence source | Can support ownership, value or condition evidence without being a Northwind integration. | Whether Northwind ever requests directly or only supports claimant retrieval/upload. | Default to evidence-upload path unless a real service arrangement is demonstrated. |

## 8. Unresolved Questions for P3.3

P3.2 should not hide uncertainty. The following questions are deliberately left open because the supplied evidence does not justify a responsible final answer. They are the concrete handoff into the P3.3 cross-review with LLL263.

- **Police TCR authority:** in what circumstances can Northwind act for a claimant, and what proof of authority would be required?
- **Vehicle recovery ownership:** is the intended service claimant-arranged, staff-arranged, insurer-network dispatch, or only guidance?
- **Repair pathway:** does the prototype distinguish claimant-selected repairers from insurer-authorised or panel repairers?
- **Assessor workflow:** who may appoint an assessor, when should the WorkItem be created, and what external status is actually observable?
- **FENZ information:** should the prototype guide the claimant to request it, allow staff to prepare a request, or simulate an insurer-side request?
- **MetService evidence:** is Northwind using public information, a formal historical report, or a simulated evidence provider?
- **Tractable access:** is there any evidenced commercial/technical access for Northwind, or should this remain a simulation/candidate capability only?
- **NHC:** what concrete Home workflow state belongs in the prototype, and should Contents have any separate non-NHCover natural-hazard evidence path?
- **ACC and health providers:** are they part of the actionable service catalogue or only a constraint example showing that system availability does not create authority?
- **Retailers, banks and valuers:** should Northwind ever request evidence directly, or should the default product path remain claimant retrieval and upload?

## 9. Implementation-Facing Service Matrix

This matrix does not create new provider capability. It translates the evidence into a form that P3.3, P5 and later implementation cards can use without re-reading the full report. "Prototype treatment" describes the safest evidence-backed representation, not a claim that live integration exists.

| Service / evidence | Scenario | Real problem solved | Timing | Owner | Authority | Output/state | Can FNOL continue while pending? | Prototype treatment |
|---|---|---|---|---|---|---|---|---|
| Police 105 reporting | Motor / theft | Record incident with Police when relevant | Now / early | Claimant | Claimant | Report/reference may be pending | Yes | Guidance/link; preserve report/reference state |
| Traffic Crash Report | Motor | Later authoritative crash evidence | Later | Claimant or authorised agent | Explicit authority | Requested / pending / received | Yes | Pending external evidence; no unrestricted API claim |
| Vehicle recovery | Motor | Move undriveable vehicle / restore mobility | Immediate | Claimant or insurer | Service authority varies | Prepared / accepted / completed / failed | Usually | Operational service; provider/access state separate |
| Repairer / quote | Motor | Determine repair option and cost | Later | Claimant or insurer | Appointment/approval varies | Quote / repair status | Yes | WorkItem or evidence source |
| Emergency contractor | Home | Stop continuing damage / make safe | Immediate | Claimant or insurer | Situation-dependent | Job/status/evidence | No if unsafe; otherwise yes | Urgent mitigation service |
| Assessor / engineer | Motor / Home | Professional damage or structural assessment | Later | Insurer | Staff/system authority | Report pending/received | Yes | Insurer-owned WorkItem |
| FENZ information | Home / fire | Authoritative event evidence | Later | Claimant or staff | Request authority | Request pending / response received | Yes | Pending external evidence |
| MetService evidence | Home | Weather/event verification | Later | Insurer/staff | Data/service access | Evidence retrieved / unavailable | Yes | Evidence retrieval only |
| NHC process | Home natural hazard | Coordinate NHCover handling | After notification | Insurer | Agency framework | Process/status | Yes | Insurer-mediated Home workflow |
| Retailer / bank / valuer evidence | Contents | Prove ownership/value/condition | As needed | Claimant by default | Claimant | Evidence available / unavailable | Yes | Claimant retrieval + upload; direct integration unproven |
| Tractable-style damage analysis | Motor | Assist visible damage assessment | Later / optional | Insurer/professional | Commercial/data authority unproven | Analytical evidence | Yes | Simulation/candidate capability unless access proven |

## 10. Implications for the Northwind Validation Prototype

1. **Trigger services by claimant need, not technical availability.** An undriveable vehicle should raise recovery before damage-analysis technology; an active leak should raise mitigation before detailed property assessment.
2. **Every external task must have an owner.** If an engineer report will be arranged by the insurer, the claimant should not repeatedly be asked to provide it.
3. **Separate business-service state from technical-integration state.** A real service may exist while Northwind only provides guidance; a simulated provider may return a demo result without any real external request occurring.
4. **Status language must say what was actually accepted.** A towing provider accepting a job is not the same as the insurer accepting a claim, and provider acknowledgement is not evidence that a requested report exists.
5. **Pending external work should not unnecessarily block FNOL.** The realistic objective is a Claim Context sufficient for the next safe action while unresolved material remains visible and owned.

For every third-party interaction the service model should answer:

- What is needed?
- Why is it needed?
- Who is responsible?
- Is it needed now?
- What authority is required?
- What has actually happened?
- Can the claim continue while this remains unresolved?

This is more useful to an FNOL system than a simple catalogue of provider endpoints.

## 11. Conclusion

The evidence from New Zealand insurance practice does not support a model of FNOL in which success means collecting every possible document and automatically executing every relevant third-party service. Real FNOL operates under uncertainty. Information arrives at different times. Different actors own different tasks. Public services and professional providers impose their own authority rules. Physical services, documentary evidence and specialist assessments behave differently. Digital integrations may exist privately without being available to Northwind.

Motor, Home and Contents also fail in different ways: Motor is shaped by incident participants, mobility and Police evidence; Home by continuing risk, mitigation and later professional assessment; Contents by proof of ownership and evidence acquisition.

The central design conclusion is therefore that Northwind should optimise for coordination rather than apparent completeness. A strong FNOL Agent should know when it has enough information to move forward, recognise what remains unresolved, assign responsibility for that unresolved work, explain the next appropriate action and accurately distinguish between a suggestion, a prepared request, an attempted external action and a verified external result.

The question for every third-party interaction should not simply be "Can Northwind integrate with this provider?" It should first be:

> "What real insurance problem does this stakeholder solve at this point in the claim, who is authorised to involve them, and what evidence would prove that the action actually occurred?"

## Appendix A. Source Register and Evidence Limits

The source titles below are reproduced from the supplied P3.2 report. The supplied PDF listed them as numbered sources but did not reproduce the underlying URLs. This register therefore adds analytical use and evidence limits without inventing missing links. Exact URLs should be inserted only from the original research notes or a fresh source verification step.

| ID | Source | Type | Used to support | Does not prove |
|---|---|---|---|---|
| S01 | Insurance Council of New Zealand - Annual Report 2025 | Industry body | Claims volume and complaint context | Does not prove any specific Northwind workflow or provider access. |
| S02 | Insurance Council of New Zealand - North Island weather events claims 96% settled | Industry body | Catastrophe claim scale and differing settlement progress | Does not define claim-state or third-party authority. |
| S03 | New Zealand Police - Use 105 | Government | Non-emergency Police reporting exists | Does not prove Northwind can report on behalf of a claimant. |
| S04 | New Zealand Police - Traffic crash reporting | Government | Crash reporting process and staged evidence context | Does not prove a public machine interface. |
| S05 | New Zealand Police - Request a Traffic Crash Report | Government | Separate TCR request process and authority relevance | Does not prove unrestricted insurer or API access. |
| S06 | Natural Hazards Commission Toka Tu Ake - About NHCover | Crown entity | Current NHCover scope used to qualify Home vs Contents relevance | Does not by itself define Northwind implementation. |
| S07 | Natural Hazards Commission Toka Tu Ake - Claims process | Crown entity | Private-insurer-mediated natural-hazard process | Does not prove a direct Northwind-to-NHC integration. |
| S08 | Fire and Emergency New Zealand - Official information requests | Government | Asynchronous external evidence request model | Does not prove a synchronous FNOL service or Northwind authority. |
| S09 | ACC - Lodging a claim for a patient | Crown entity | Provider eligibility and patient-authorisation boundary | Does not permit Northwind to lodge injury claims. |
| S10 | MetService - Weather analysis and reporting | Authoritative provider | Weather evidence availability | Does not establish coverage, liability or claim acceptance. |
| S11 | Tower - Hello Claims and Panel Quote integration | Insurer / implementation example | Real insurer-repairer digital integration is feasible | Does not prove the same interface is public or available to Northwind. |
| S12 | Office of the Privacy Commissioner - Principle 11: Disclosure of personal information | Regulator | Disclosure/privacy boundary | Does not by itself define every service-specific consent or authority rule. |
| S13 | AA Insurance - Motor accident and repair guidance | Insurer | Motor accident/repair journey context | Does not prove AA Roadservice collision-recovery scope or Northwind access. |
| S14 | AMI - Roadside Rescue | Insurer / service guidance | Roadside-assistance example | Does not establish accident-recovery equivalence. |
| S15 | Tractable - Auto insurance solutions | Vendor | Damage-analysis capability exists in the claim domain | Does not prove Northwind contract, enterprise access, permitted data use or decision authority. |

## References

1. Insurance Council of New Zealand. *Annual Report 2025.*
2. Insurance Council of New Zealand. *North Island weather events claims 96% settled.*
3. New Zealand Police. *Use 105.*
4. New Zealand Police. *Traffic crash reporting.*
5. New Zealand Police. *Request a Traffic Crash Report.*
6. Natural Hazards Commission Toka Tu Ake. *About NHCover.*
7. Natural Hazards Commission Toka Tu Ake. *Claims process.*
8. Fire and Emergency New Zealand. *Official information requests.*
9. ACC. *Lodging a claim for a patient.*
10. MetService. *Weather analysis and reporting.*
11. Tower. *Hello Claims and Panel Quote integration.*
12. Office of the Privacy Commissioner. *Principle 11 - Disclosure of personal information.*
13. AA Insurance. *Motor accident and repair guidance.*
14. AMI. *Roadside Rescue.*
15. Tractable. *Auto insurance solutions.*
