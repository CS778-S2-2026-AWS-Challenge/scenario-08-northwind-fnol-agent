# D2-R02 - Insurance Industry Interview and Supporting User Observation

## 1. Research Purpose

This research was conducted to identify practical problems experienced by insurance staff and customers during insurance-related claim interactions.

It contains two separate evidence sources:

1. an informal interview with an insurance-industry professional; and
2. a small exploratory observation involving five participants attempting to use a real insurance claims website.

The two evidence sources are intentionally kept separate. Neither source is treated as representative of the whole insurance industry or all insurance customers.

No real customer-identifiable information, participant-identifying information, or company-confidential information is recorded.

---

## 2. Evidence Source A - Insurance Industry Interview

### 2.1 Participant Context

- **Participant role:** Insurance-industry auditor
- **Interview date:** 11 August 2026
- **Recorder:** jxu316-arch
- **Interview method:** Text-based conversation
- **Participation and recording consent:** Obtained from the participant
- **Interview type:** Informal industry interview
- **Purpose:** Identify employee-side difficulties associated with customer preparation, information requirements, and communication during insurance-related processes.
- **Privacy:** No participant name, employer name, customer data, or confidential company information is recorded.

### 2.2 Participant Statement

The participant identified a recurring problem in interactions between insurance staff and customers.

Customers often do not understand what they need to prepare, what documents are required, or what actions they are personally responsible for completing.

Some customers assume that once they contact customer service, the insurance employee should be able to resolve every part of the process for them.

However, certain documents or information may need to be obtained by the customer directly from another relevant organisation or department.

Even after staff explain that the customer must obtain these materials themselves, some customers continue asking the employee to resolve the issue on their behalf.

According to the participant, this creates difficulty for employees because substantial time can be spent repeatedly explaining the same requirements instead of progressing their normal work.

---

## 3. Staff Intake Observation

### Evidence from Participant

Customers may begin an insurance-related process without understanding:

- what documents or information are required;
- what they must obtain themselves;
- where those documents should be obtained;
- which actions the insurer can perform; and
- which actions remain the customer's responsibility.

This means that an insurance employee may receive a customer interaction before the customer is actually prepared to progress the process.

### Team Interpretation

Poor preparation and unclear responsibility boundaries may create avoidable friction during the initial intake stage.

A customer may not only be missing information; they may also lack a clear understanding of:

- what the requested information means;
- why it is required;
- where it can be obtained; and
- who is responsible for obtaining it.

This interpretation is based on one participant's experience and is not presented as an industry-wide finding.

---

## 4. Staff Workload Observation

### Evidence from Participant

Employees may spend significant time repeatedly explaining:

- what the customer needs to provide;
- why certain documents must be obtained by the customer;
- where the customer needs to obtain them; and
- why the insurance employee cannot complete every external step on the customer's behalf.

The participant described this repeated communication as disruptive to employees' ability to work efficiently.

### Team Interpretation

A portion of staff workload may come from process explanation and expectation management rather than substantive claim processing.

If customers receive clearer guidance before and during FNOL, some avoidable communication may be reduced.

This remains a design hypothesis requiring further validation.

---

## 5. Handoff Observation

Handoff was not discussed in this interview.

The participant did not provide evidence about:

- internal claim transfers;
- movement between departments;
- changes in case ownership; or
- information loss during handoff.

No handoff finding is inferred from this interview.

---

## 6. Evidence Source B - AA Insurance Website Observation

### 6.1 Method

Five participants from other project groups were asked to attempt a normal insurance claim using the public AA Insurance website.

- **Observation method:** Face-to-face
- **Participation and recording consent:** Obtained from all five participants

The participants were asked to interact with the process as ordinary users.

This was an exploratory usability observation rather than a controlled usability study.

The participants were not presented as representative insurance customers.

### 6.2 Observed Behaviour

All five participants encountered difficulty when the claims process requested information such as a **policy number**, a term that they did not normally understand or know how to locate.

At this point:

- **5/5 participants expressed a desire to abandon the process.**

A Help option was visible near the process.

However, participants reported that the available help did not sufficiently resolve the immediate problem. The help experience mainly directed users elsewhere on the website or suggested contacting customer service by telephone.

After experiencing the process:

- **5/5 participants described the website process as too troublesome and indicated that they did not want to continue.**
- **2/5 participants said that they would consider making a phone call if customer service could resolve the problem.**
- **3/5 participants said that calling customer service also felt inconvenient and that they would prefer not to continue.**

---

## 7. Communication Preference Observation

During the exercise, reluctance to make a phone call appeared to include discomfort with telephone communication.

There was an informal impression that some younger participants may feel more comfortable communicating through text than by telephone and may experience greater anxiety when calling.

This was **not formally measured** and must therefore be treated only as a preliminary observation.

It must not be presented as evidence that younger users generally dislike telephone communication.

---

## 8. Cross-Source Interpretation

The industry interview and the website observation point toward a potentially connected service problem.

### Customer-Side Friction

Customers may encounter:

- unfamiliar terminology;
- unclear document requirements;
- uncertainty about where information can be found;
- uncertainty about what they are personally responsible for doing; and
- support options that do not resolve the problem at the point where it occurs.

### Possible Customer Response

When self-service guidance does not resolve the immediate problem, customers may:

1. abandon the process;
2. contact customer service;
3. repeatedly ask staff to explain requirements; or
4. expect staff to complete steps that the customer must perform personally.

### Possible Staff Impact

This customer-side friction may then transfer into employee workload through:

- repeated explanation;
- expectation management;
- incomplete or unready intake;
- repeated customer contact; and
- time spent on procedural clarification rather than substantive claim work.

This cross-source connection is a **team interpretation**, not a direct participant statement.

---

## 9. Design Opportunity for the Northwind FNOL Agent

The research suggests that an AI-assisted FNOL experience should do more than simply collect information.

At the point where a customer becomes confused, the system should be able to explain:

- **what** the requested field or document is;
- **why** it is needed;
- **where** the customer can find or obtain it;
- **who** is responsible for obtaining it;
- **what to do if the customer does not currently have it**; and
- **what happens next**.

For unfamiliar fields such as a policy number, support should ideally be contextual and immediate rather than only redirecting the user to another page or telephone support.

The system should also support customers who cannot complete a required step immediately, rather than forcing them to abandon the entire process.

These are design opportunities derived from the evidence and should be validated further.

---

## 10. Evidence Traceability

| Evidence ID | Source | Direct Evidence | Interpretation |
|---|---|---|---|
| INT-01 | Insurance-industry auditor interview | Customers may not understand what they need to prepare or do themselves. | Intake guidance and responsibility clarity may be insufficient. |
| INT-02 | Insurance-industry auditor interview | Customers may continue asking staff to handle tasks they must complete themselves. | Repeated explanation may create avoidable staff workload. |
| INT-03 | Insurance-industry auditor interview | Repeated customer explanation consumes employee time. | Better pre-intake guidance may reduce procedural workload. |
| OBS-01 | AA Insurance exploratory observation, n=5 | 5/5 expressed a desire to abandon when encountering unfamiliar information such as policy number. | Unfamiliar terminology may create a significant abandonment point. |
| OBS-02 | AA Insurance exploratory observation, n=5 | Available Help did not sufficiently resolve the immediate issue for participants. | Contextual help may be more useful than redirects or generic support. |
| OBS-03 | AA Insurance exploratory observation, n=5 | 5/5 described the process as too troublesome to continue. | Process friction may discourage completion. |
| OBS-04 | AA Insurance exploratory observation, n=5 | 2/5 would consider calling; 3/5 did not want to call. | Telephone-only escalation may not suit every user. |
| OBS-05 | Informal observation during usability exercise | Some participants appeared uncomfortable with phone communication. | Possible preference for text-based support; requires further validation. |

---

## 11. Evidence Limitations

### Industry Interview

The insurance-industry evidence comes from a single participant.

It must not be presented as proof that all insurance employees, insurers, or claims teams experience the same problem.

The interview did not cover internal handoff, so no handoff conclusion is drawn.

### AA Insurance Observation

The website observation involved only five participants and was exploratory rather than statistically representative.

The participants were members of other project groups rather than a formally recruited representative sample of insurance claimants.

The exercise therefore identifies possible usability problems and design hypotheses rather than population-level prevalence.

The observation that younger users may prefer text communication was not formally tested and must remain provisional.

### Further Validation

Future research could validate these findings with:

- additional insurance staff;
- actual insurance claimants;
- a larger usability sample;
- structured questions about communication-channel preferences; and
- direct testing of contextual AI guidance.

---

## 12. Acceptance Check for Issue #21

- [x] No real customer data is recorded.
- [x] No company-confidential information is recorded.
- [x] The single industry interview is not presented as an industry-wide finding.
- [x] Participant statements are separated from team interpretation.
- [x] Staff intake observations are clearly identified.
- [x] Staff workload observations are clearly identified.
- [x] Handoff is explicitly recorded as not discussed rather than inferred.
- [x] The AA Insurance observation is clearly separated from the industry interview.
- [x] Preliminary observations are labelled as requiring further validation.

---

## 13. Research Summary

The strongest combined finding is a gap between **what insurance processes require customers to know** and **what ordinary customers actually understand when they begin the process**.

The insurance-industry participant described the employee-side consequence: customers may repeatedly ask staff to explain or perform actions that the customer must complete themselves.

The AA Insurance observation showed a corresponding customer-side problem: all five participants became unwilling to continue when they encountered unfamiliar requirements such as a policy number, and the available Help did not sufficiently resolve their immediate uncertainty.

Together, these findings support a design direction in which the Northwind FNOL Agent provides contextual, step-by-step guidance at the moment of confusion while clearly explaining customer responsibilities and escalation options.
