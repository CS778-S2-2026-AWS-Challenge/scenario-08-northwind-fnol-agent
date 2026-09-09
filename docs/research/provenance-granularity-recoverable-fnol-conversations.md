# Provenance Granularity for Recoverable FNOL Conversations

*A Paired Pilot Study of Full-Message, Minimal-Span, and Adaptive Evidence Retrieval*

**Northwind Insurance FNOL Agent - COMPSCI 778 AWS Challenge**

Research analysis based on the current repository architecture, a 30-case synthetic paired benchmark,
and published dialogue / LLM research.

**Revised September 2026**

## Abstract

Recoverable First Notice of Loss (FNOL) systems must preserve claim progress across interrupted
conversations without relying on a language model to reconstruct business state from an unbounded
chat history. The Northwind FNOL architecture instead maintains authoritative structured Claim State
in the backend Runtime, records field status and message-level source references, persists complete
messages, and stores bounded resume information. This study examines whether a field should
additionally point to the exact text span that supported its value. We frame the question as a
provenance-granularity trade-off rather than as a search for a universally finer representation.

A paired synthetic benchmark of 30 FNOL cases compared full-message retrieval with minimal
field-span retrieval while holding structured Claim State and Resume Context constant. Under normal
resume conditions, both approaches preserved the required recovery semantics in 30/30 cases. Under
deliberately degraded resume information, full-message retrieval preserved critical semantics in
30/30 cases and minimal spans in 16/30; all 14 discordant pairs favoured full-message retrieval
(exact McNemar / exact binomial test, two-sided p = 0.000122). In a 12-case difficult behavioral
subset, both approaches produced the correct next workflow action in 12/12 cases, but critical
continuity details were preserved in 12/12 full-message cases versus 4/12 minimal-span cases; all
eight discordant pairs favoured full-message retrieval (two-sided p = 0.007813).

Minimal spans reduced retrieved source-text characters by 71.3% on average, with an 81.0% reduction
in long multi-field cases. These results are exploratory: the cases were synthetic and the same
model family participated in case construction and evaluation. The evidence therefore supports
conditional rather than universal superiority. The current message-level design remains the stronger
default, while contextual spans or adaptive field-aware retrieval are plausible extensions for long,
dense, ambiguous, disputed, or audit-sensitive inputs.

**Keywords:** FNOL; dialogue state tracking; provenance; context granularity; long-context LLMs;
recoverable dialogue; insurance AI; adaptive retrieval.

## 1. Introduction

A claimant may begin an FNOL interaction, provide only part of the required information, leave, and
return hours or days later. A reliable system must resume the same Claim without re-asking confirmed
information or silently converting tentative statements into facts. This creates two related but
distinct recovery problems: workflow-state recovery (what the system should do next) and
semantic-evidence recovery (why a field has its current value and status). Audit provenance is a
third concern: a staff member may need to inspect the original claimant statement that supports a
structured field.

The Northwind implementation already separates these concerns. Runtime-owned structured state
carries field value and status; bounded session-resume information carries unfinished work and
commitments; complete messages remain persisted; and structured fields carry message-level source
references. The design question is therefore narrower than "how should an LLM remember a
conversation?" It is whether a field-level exact text span provides sufficient additional value over
an existing message reference to justify new schema, extraction, validation, and maintenance
complexity.

This study asks three research questions:

- **RQ1 - Recovery accuracy:** Does minimal-span retrieval improve routine FNOL recovery when
  Runtime-owned structured state and Resume Context are available?
- **RQ2 - Semantic robustness:** When resume information is incomplete, which provenance
  granularity better preserves correction, negation, uncertainty, temporal relations, and
  cross-sentence evidence?
- **RQ3 - Efficiency and architecture:** When does finer retrieval reduce irrelevant source text
  enough to justify its additional engineering cost, and should the system use a fixed or adaptive
  granularity?

## 2. Current Northwind Architecture

### 2.1 Authoritative structured Claim State

The current repository models each structured form field with a value, source, `source_refs`,
status, `needed_for`, confidence, `updated_at`, and `updated_by`. The available field states include
`proposed`, `confirmed`, `disputed`, `missing`, and `pending_generation`. This is important because
the presence of a value does not imply that the value is confirmed. A resumed model does not need
to infer that distinction from old prose if Runtime already exposes the structured status.

> **Repository evidence.** The current `StructuredFormField` contract contains `source_refs` and
> explicit status metadata. The repository readiness documentation also identifies those fields as
> part of the existing structured form contract. This means the baseline already has provenance;
> the open design question is provenance granularity, not provenance versus no provenance.

### 2.2 Message-level provenance and Resume Context

The current design can associate multiple fields with the same claimant message. For a short
message, that association may be almost as informative as an exact span. For a long message that
supplies many facts, it is coarser: incident time, location, damage, and vehicle drivability may all
point to the same message ID.

Separately, the session layer contains bounded recovery information such as a summary, unresolved
questions, pending items, and prior commitments. The current Week 6 P17.1 work item explicitly
targets incomplete-Claim persistence, recovery context, last meaningful interaction, and follow-up
tasks while avoiding duplicate Claims.

### 2.3 Why Runtime changes the provenance problem

In a conventional model-only chatbot, provenance may be necessary just to rediscover the current
state. In Northwind, Runtime is intended to own that state. If `incident_time = 20:00` and
`status = proposed`, the next interaction should seek confirmation even if the model never rereads
the original sentence. Consequently, provenance retrieval is most valuable for semantic
explanation, ambiguity resolution, correction history, and audit - not as the primary source of
workflow truth.

## 3. Compared Provenance Designs

| Design | Representation | Main advantage | Main risk |
| --- | --- | --- | --- |
| A. Full-message retrieval | `field -> message_id -> complete immutable message` | Preserves all local linguistic context; simplest authoritative evidence path | May include irrelevant text when messages are long or dense |
| B. Minimal-span retrieval | `field -> message_id -> smallest supporting text span` | Precise location; reduces retrieved source text | Span selection can truncate negation, correction, uncertainty, or cross-sentence relations |
| C. Contextual-span retrieval | `field -> message_id -> relevant span plus neighbouring sentence/window` | Balances precision with relational context | Still requires indexing, boundary policy, and testing |
| D. Adaptive retrieval | Runtime chooses no retrieval, full message, or contextual span by field/message condition | Matches granularity to the task and risk | More policy logic; requires production evidence for trigger thresholds |

The pilot directly evaluates A versus B. Designs C and D are not experimentally validated here;
they are architectural hypotheses derived from the observed failure modes and the literature on
dynamic dialogue-context selection.

## 4. Related Research

### 4.1 Dialogue state tracking and context granularity

Dialogue State Tracking (DST) is the closest established research analogue to FNOL form completion
because it maintains structured slot-value state across natural-language turns. Yang, Huang, and
Mao [1] show that context at different granularities plays different roles: full-history "scratch"
prediction can introduce noise for short-dependency states, while update-from-previous-state methods
may miss long dependencies. Their results motivate combining granularities rather than treating one
fixed context size as universally optimal.

LUNA [2] makes the connection to the Northwind baseline more direct. Instead of using all dialogue
turns for every slot, it explicitly aligns each slot with its most relevant utterance and then
predicts the value from that aligned turn. The authors argue that irrelevant utterances can be
useless or confusing. DiCoS-DST [3] similarly selects different dialogue content for different slots
and turns, explicitly aiming to reduce insufficient or redundant context. These studies support
message- or turn-level retrieval as a meaningful filter, not merely as a crude implementation
shortcut.

### 4.2 Span extraction and provenance

TripPy [4] demonstrates that exact text spans can be useful for extractive slot-value prediction,
while later work by Heck et al. [5] shows that robust extractive DST can be trained without
fine-grained manual span labels. These results establish that span-level evidence is technically
meaningful. However, their primary task is extracting a current state, not deciding what provenance
should be persisted and reloaded after a backend Runtime has already stored the state. A useful
extraction mechanism is therefore not automatically a sufficient argument for mandatory span
persistence.

Provenance research provides the complementary argument for retaining an authoritative original
source. Zhang, Ives, and Roth [6] formalize provenance for natural-language claims in terms of where
a claim came from and how it evolved, and demonstrate usefulness for claim verification. In an
insurance workflow, that supports preserving the full claimant message even if a smaller span is
stored as an index or UI highlight.

### 4.3 Long-context and long-term memory evidence

Long-context capacity does not eliminate the cost of irrelevant or excessive context. Liu et al.
[7] show that long-context models can use evidence unevenly depending on where it appears, with
substantial degradation when relevant information is in the middle of a long context. Du et al. [8]
later isolate context length from retrieval quality and report performance degradation of
13.9%-85% across five models as input length increases, even when relevant evidence is perfectly
retrievable. These findings justify minimizing unnecessary context in principle, but they mostly
concern inputs far larger than the tens or hundreds of characters in this pilot; they should not be
used to claim that a 200-character claimant message is inherently problematic.

Long-term dialogue research also favours structured, selective memory over unbounded replay. LoCoMo
[9] contains conversations averaging about 600 turns and 16K tokens and finds that long-context and
RAG approaches still struggle with long-range temporal and causal understanding. Reflective Memory
Management (RMM) [10] explicitly argues that rigid memory granularity can fragment or incompletely
represent conversational information, and dynamically manages memory at utterance, turn, and
session levels. RMM reports more than 10% accuracy improvement over a no-memory-management baseline
on LongMemEval. This literature is consistent with an adaptive rather than fixed provenance
granularity.

## 5. Pilot Methodology

### 5.1 Synthetic paired benchmark

We constructed 30 synthetic FNOL cases representing four scenario classes. Every case was evaluated
under both retrieval conditions, making this a paired design rather than a comparison of two
independent samples.

| Scenario class | n | Purpose |
| --- | ---: | --- |
| Short single-field | 8 | Test whether exact spans add value when a message is already nearly atomic |
| Long multi-field | 8 | Test source-text reduction and field isolation when one narrative populates several fields |
| Uncertainty / correction | 8 | Test preservation of tentative language, self-correction, competing values, and commitments |
| Cross-context | 6 | Test negation, safety interpretation, temporal distinction, and evidence spanning more than one clause |

### 5.2 Controlled comparison

For each case, the structured Claim State was held constant. In the normal condition, both designs
also received a case-specific Resume Context containing the relevant unresolved work. The only
provenance difference was whether the retrieved source was the complete message (A) or a
deliberately minimal field span (B). A stress condition replaced the detailed resume with a generic
continuation cue, increasing dependence on provenance retrieval.

A 12-case difficult subset was then used for a behavioral comparison of:

1. Next-action correctness.
2. Preservation of critical continuity details.

### 5.3 Outcomes and statistical analysis

The primary outcomes were binary per case: whether critical recovery semantics were available,
whether the next workflow action was correct, and whether correction/negation/uncertainty or other
continuity details were preserved. Because every case was observed under both A and B, discordant
paired outcomes were analysed with an exact McNemar test. When all discordant pairs favour one
condition, the exact test is equivalent to a two-sided exact binomial test on the discordant pairs
under p = 0.5. We report raw counts and exact p-values rather than treating the paired observations
as independent proportions.

Source-text efficiency was measured using character counts as a model-independent proxy for
retrieved source volume. This is not presented as a production token-cost measurement. A proper
deployment study should use the exact model provider usage counters for input tokens, latency, and
monetary cost.

## 6. Results

### 6.1 Normal recovery: no observed advantage for minimal spans

| Outcome | Full message | Minimal span | Paired interpretation |
| --- | ---: | ---: | --- |
| Critical recovery semantics available | 30/30 | 30/30 | No discordant pairs; no evidence of a recovery advantage for either design in this condition |
| Next action correct (difficult subset) | 12/12 | 12/12 | No discordant pairs; Runtime-owned structured state neutralised most workflow differences |

When Resume Context was complete, minimal spans did not improve the measured recovery outcome. This
is consistent with the architecture: structured field status already tells Runtime whether a value
is confirmed, proposed, disputed, or missing. Provenance retrieval therefore contributes less to
routine next-step selection than it would in a model-only memory design.

### 6.2 Stress condition: full messages preserved more semantic context

| Paired outcome under degraded Resume | Count |
| --- | ---: |
| Both full-message and minimal-span preserved the required semantics | 16 |
| Full-message succeeded; minimal-span failed | 14 |
| Minimal-span succeeded; full-message failed | 0 |
| Both failed | 0 |

Full-message retrieval preserved critical semantics in 30/30 cases, compared with 16/30 for minimal
spans. The inferential evidence comes from the paired pattern: all 14 discordant cases favoured
full-message retrieval. Under the exact McNemar / exact binomial test, the one-sided probability is
0.000061 and the two-sided p-value is 0.000122. Within this synthetic benchmark, the directional
difference is therefore unlikely to be explained by random paired outcome variation alone.

> **Statistical boundary.** This p-value does not repair construct bias. The cases were synthetic,
> and the same model family participated in case construction and evaluation. Statistical
> significance within the benchmark is not evidence that the same effect size will occur in real
> claimant traffic.

### 6.3 Difficult behavioral subset: same workflow action, different continuity quality

| Paired outcome for critical continuity detail | Count |
| --- | ---: |
| Both designs preserved the detail | 4 |
| Full-message preserved it; minimal-span did not | 8 |
| Minimal-span preserved it; full-message did not | 0 |
| Neither preserved it | 0 |

Both designs produced the correct next workflow action in all 12 difficult cases. However,
full-message retrieval preserved critical continuity details in 12/12 cases, while minimal spans did
so in 4/12. All eight discordant pairs favoured full-message retrieval; the exact one-sided
probability is 0.003906 and the two-sided p-value is 0.007813.

This separation between workflow accuracy and continuity quality is a central architectural
finding: Runtime-owned state can keep the process on the right branch even when the model receives
a weaker explanation of how the field reached that state.

**Figure 1. Paired pilot outcome counts.** Percentages are avoided because the benchmark is small;
raw paired counts carry the important information.

| Evaluation condition | Full message | Minimal span |
| --- | ---: | ---: |
| Normal semantic availability (n=30) | 30 | 30 |
| Stress semantic preservation (n=30) | 30 | 16 |
| Behavioral critical nuance (n=12) | 12 | 4 |

### 6.4 Source-text efficiency

| Scenario class | Complete message mean (characters) | Minimal span mean (characters) | Reduction |
| --- | ---: | ---: | ---: |
| Short single-field | 12.5 | 10.25 | 18.0% |
| Long multi-field | 88.63 | 16.88 | 81.0% |
| Uncertainty / correction | 38.25 | 13.38 | 65.0% |
| Cross-context | 46.5 | 12.67 | 72.8% |
| All 30 cases | 46.47 | 13.33 | 71.3% |

The overall 46.47-character mean is not inconsistent with the longer examples used in the paper:
the benchmark deliberately contains eight very short single-field messages averaging only 12.5
characters, which pulls down the overall mean. Long multi-field cases average 88.63 characters and
show the largest relative reduction. Character reduction is therefore real in the pilot, but its
share of a complete model request is unknown because the system prompt, Claim State, Runtime policy,
Resume Context, and other structured inputs were not token-metered.

**Figure 2. Reduction in retrieved source-text characters from minimal-span retrieval.** This is a
source-volume proxy, not a measured API token or cost reduction.

| Scenario class | Reduction in retrieved source-text characters |
| --- | ---: |
| Short single-field | 18.0% |
| Long multi-field | 81.0% |
| Uncertainty / correction | 65.0% |
| Cross-context | 72.8% |

## 7. Interpretation

### 7.1 Why minimal spans did not improve routine recovery

The baseline architecture has already moved the most important recovery decisions out of
conversational memory. A proposed incident time remains proposed because the structured field says
so, not because a new model correctly rereads "I am not sure." A previously confirmed location need
not be rediscovered from prose. This explains why next-action accuracy remained 12/12 in both
conditions: the Runtime contract absorbs much of the workflow burden that span indexing might
otherwise solve.

### 7.2 Why minimal spans failed under semantic stress

Minimal spans can remove precisely the language that gives a value its epistemic or temporal
meaning. "The car can still start" is not enough when the next clause says the steering wheel cannot
turn and the vehicle is unsafe to drive. "Around 8:30" is not enough when the earlier clause says it
is a correction of a previous 8:00 estimate and remains uncertain. "No visible injury" is not
enough when the next sentence reports dizziness and a plan to attend hospital. These are not mere
value-extraction problems; they are relational-semantic problems involving negation, contrast,
correction, causality, and cross-sentence scope.

This also reveals an important limitation of the B condition itself: a minimal span is a selected
representation. Its boundary can be wrong. A message ID points to immutable source evidence,
whereas a span adds a second model or heuristic decision about which characters count as the
evidence. Fine granularity can therefore create provenance truncation error even while improving
locational precision.

### 7.3 What span indexing still offers

The pilot does show a credible efficiency benefit in long multi-field narratives. If production
users provide hundreds or thousands of tokens in one message and a single turn populates many
fields, repeatedly retrieving the complete narrative for each field may become wasteful. A
field-aware index could also improve staff interfaces by highlighting likely evidence immediately
while still allowing expansion to the full message. The evidence therefore argues against
mandatory minimal spans, not against all fine-grained indexing.

## 8. Conditional Superiority: Which Design Is Better When?

| Situation | Preferred retrieval | Reason |
| --- | --- | --- |
| Short, single-field message | Full message or no provenance retrieval | The message is already close to atomic; span maintenance adds little value |
| Short message with several fields | Full message | Re-reading cost is small and relational context remains intact |
| Very long, multi-field narrative | Contextual span / field-aware retrieval | Potentially large reduction in irrelevant text while keeping neighbouring context |
| Correction, negation, uncertainty, competing values | Full message or wide contextual window | Meaning often depends on clauses outside the minimal value span |
| Safety-sensitive, disputed, or review-sensitive field | Full message remains authoritative | Audit and risk review require access to complete source evidence |
| Staff audit / explainability UI | Span highlight + full-message expansion | Fine location helps inspection but should not replace the source of truth |
| Normal recovery with strong structured state | Often no provenance retrieval is needed | Runtime state can determine the workflow action without rereading evidence |

The resulting conclusion is conditional superiority rather than a universal winner. Message-level
retrieval is the safer default for the current system. Fine-grained retrieval becomes more
attractive as message length, field density, or audit-navigation cost increases; full local context
becomes more valuable as semantic dependence and risk increase.

## 9. Proposed Architecture: Adaptive Provenance Retrieval

A future design should preserve a single authoritative source chain and adapt only the retrieval
view:

- **Source of truth:** `field -> message_id -> complete immutable claimant message`.
- **Optional index:** `field -> one or more evidence spans`, used as hints rather than as replacement
  evidence.
- **Context expansion:** When a span is used, retrieve its containing sentence and/or neighbouring
  context rather than the smallest value token by default.
- **Runtime policy:** Choose no retrieval, contextual-span retrieval, or full-message retrieval based
  on field status, message length, field density, uncertainty, correction/dispute indicators, and
  safety/review sensitivity.

> **Recommended default.** Do not change the current core persistence contract merely to replace
> message references with spans. If production telemetry later shows long claimant narratives,
> context-noise errors, or material token/latency cost, add spans as optional indexes while retaining
> `message_id` as authoritative provenance.

This architecture aligns with the literature: LUNA and DiCoS-DST support slot-specific selection;
Yang et al. and RMM support multiple or dynamic granularities; provenance work supports retaining
the original source; and the pilot identifies concrete cases where both over-broad and over-narrow
retrieval can be suboptimal.

## 10. Threats to Validity

### 10.1 Conclusion validity

The paired design is stronger than treating the two conditions as independent samples because every
FNOL case serves as its own control. Exact McNemar tests quantify the one-directional discordance in
the stress and continuity outcomes. However, n = 30 and n = 12 remain small, multiple outcomes were
inspected, and the binary scoring rubric collapses gradations of response quality. The exact
p-values therefore describe consistency within this benchmark, not precise production effect sizes.

### 10.2 Construct validity

This is the most serious threat. The benchmark, minimal spans, behavioral responses, and evaluation
were produced within the same model-assisted workflow. The experiment therefore risks
"self-generated test" bias: the cases may encode the evaluator's assumptions about what makes full
messages or spans succeed. In addition, the B condition tests deliberately minimal spans; it does
not test every possible span system. A contextual-span design could perform materially better.
These construct limitations cannot be corrected by statistical significance.

### 10.3 Internal validity

Although Claim State and Resume inputs were held constant within a pair, other modelling choices
can influence the result: how a span boundary is chosen, how degraded Resume Context is phrased,
and how the gold criterion defines "critical continuity detail." Synthetic sentences are also
cleaner and more explicitly contrastive than many real reports. These factors provide alternative
explanations for the size of the observed effect.

### 10.4 External validity

The benchmark is not a sample of real Northwind claimant traffic. Real FNOL language may contain
typos, speech-to-text errors, incomplete grammar, repeated corrections, code-switching, emotionally
distressed phrasing, irrelevant narrative, and much longer or much shorter turns. Production prompts
also contain provider-specific tokenisation, system instructions, latency, and pricing that were not
measured. The results should therefore guide architecture hypotheses, not be extrapolated directly
to production accuracy or cost.

## 11. Implications for P17.1 and the Current Project

For the current incomplete-Claim recovery work, the evidence supports prioritising the existing
architectural responsibilities: persist the incomplete Claim and its status; persist bounded
recovery context and follow-up work; keep the same Claim identity on resume; and make
missing/stale/non-resumable situations explicit.

Message-level provenance already provides an authoritative path back to the claimant statement.
Mandatory span persistence would expand contracts and tests without demonstrated improvement to
routine next-action recovery in this pilot.

The research is still useful even if no immediate schema change is made. It identifies a measurable
future optimisation point. If production or higher-fidelity testing shows that claimant messages
become long and multi-field, the team can introduce contextual-span retrieval behind the existing
message reference rather than redesigning the source of truth.

## 12. Conclusion and Future Evaluation

This study separates three functions that are often conflated in LLM systems: workflow-state
recovery, semantic-evidence recovery, and audit provenance. In Northwind, Runtime-owned structured
state already solves much of the first function. That changes the value proposition of finer
provenance: an exact span is not primarily needed to decide what to ask next; it is potentially
useful for efficiently retrieving and explaining the evidence behind a field.

The paired pilot provides two simultaneous signals. First, minimal spans dramatically reduce
retrieved source-text volume in long messages. Second, when contextual recovery information is weak,
overly narrow spans can lose correction, negation, uncertainty, and cross-sentence meaning. The
exact paired tests show that this directional pattern is strong within the synthetic benchmark, but
the construct and external-validity threats are substantial enough that the result should not be
framed as production proof.

The next experiment should therefore test three or four conditions rather than repeat the current
binary comparison: full message, minimal span, contextual span, and an adaptive policy. A fixed
benchmark should be frozen before evaluation; A/B/C/D prompts should be blinded; multiple
independent runs and at least one independent human or model judge should be used; and real input
tokens, latency, and cost should be recorded.

No architectural optimisation should override production evidence: if real FNOL telemetry shows
that full-message retrieval remains cheap and reliable, the simpler design should remain. If long
narratives create measurable cost or context-noise failures, contextual or adaptive retrieval
becomes justified by evidence rather than intuition.

## References

1. P. Yang, H. Huang, and X.-L. Mao. 2021. *Comprehensive Study: How the Context Information of
   Different Granularity Affects Dialogue State Tracking?* ACL-IJCNLP 2021, pp. 2481-2491.
   DOI: 10.18653/v1/2021.acl-long.193.
2. Y. Wang, J. Zhao, J. Bao, C. Duan, Y. Wu, and X. He. 2022. *LUNA: Learning Slot-Turn Alignment
   for Dialogue State Tracking.* NAACL 2022, pp. 3319-3328.
   DOI: 10.18653/v1/2022.naacl-main.242.
3. J. Guo, K. Shuang, J. Li, Z. Wang, and Y. Liu. 2022. *Beyond the Granularity:
   Multi-Perspective Dialogue Collaborative Selection for Dialogue State Tracking.* ACL 2022,
   pp. 2320-2332. DOI: 10.18653/v1/2022.acl-long.165.
4. M. Heck, C. van Niekerk, N. Lubis, C. Geishauser, H.-C. Lin, M. Moresi, and M. Gasic. 2020.
   *TripPy: A Triple Copy Strategy for Value Independent Neural Dialog State Tracking.* SIGDIAL
   2020, pp. 35-44. DOI: 10.18653/v1/2020.sigdial-1.4.
5. M. Heck, N. Lubis, C. van Niekerk, S. Feng, C. Geishauser, H.-C. Lin, and M. Gasic. 2022.
   *Robust Dialogue State Tracking with Weak Supervision and Sparse Data.* Transactions of the
   Association for Computational Linguistics 10:1175-1192. DOI: 10.1162/tacl_a_00513.
6. Y. Zhang, Z. Ives, and D. Roth. 2020. *"Who said it, and Why?" Provenance for Natural Language
   Claims.* ACL 2020, pp. 4416-4426. DOI: 10.18653/v1/2020.acl-main.406.
7. N. F. Liu, K. Lin, J. Hewitt, A. Paranjape, M. Bevilacqua, F. Petroni, and P. Liang. 2024.
   *Lost in the Middle: How Language Models Use Long Contexts.* Transactions of the Association
   for Computational Linguistics 12:157-173. DOI: 10.1162/tacl_a_00638.
8. Y. Du, M. Tian, S. Ronanki, S. Rongali, S. B. Bodapati, A. Galstyan, A. Wells, R. Schwartz,
   E. A. Huerta, and H. Peng. 2025. *Context Length Alone Hurts LLM Performance Despite Perfect
   Retrieval.* Findings of EMNLP 2025, pp. 23281-23298.
   DOI: 10.18653/v1/2025.findings-emnlp.1264.
9. A. Maharana, D.-H. Lee, S. Tulyakov, M. Bansal, F. Barbieri, and Y. Fang. 2024.
   *Evaluating Very Long-Term Conversational Memory of LLM Agents.* ACL 2024, pp. 13851-13870.
   DOI: 10.18653/v1/2024.acl-long.747.
10. Z. Tan, J. Yan, I.-H. Hsu, R. Han, Z. Wang, L. Le, Y. Song, Y. Chen, H. Palangi, G. Lee,
    A. R. Iyer, T. Chen, H. Liu, C.-Y. Lee, and T. Pfister. 2025. *In Prospect and Retrospect:
    Reflective Memory Management for Long-term Personalized Dialogue Agents.* ACL 2025,
    pp. 8416-8439. DOI: 10.18653/v1/2025.acl-long.413.

## Appendix A. Reproducibility Notes

The pilot workbook contains the 30 synthetic cases, scenario class, full message, minimal span,
structured Claim State, case-specific normal Resume Context, gold action, source-text character
counts, stress-condition semantic scores, and the 12-case behavioral outputs.

The paired statistical results can be reproduced directly from the discordant counts:

- For 14 discordant stress cases all favouring full-message:
  `2 x (0.5^14) = 0.0001220703`.
- For eight discordant continuity cases all favouring full-message:
  `2 x (0.5^8) = 0.0078125`.

Normal recovery and next-action outcomes contain no discordant pairs and therefore provide no
comparative McNemar statistic.

The source-text character means used in Section 6.4 were recomputed from the stored strings:

- Overall complete message = 46.4667 characters.
- Overall minimal span = 13.3333 characters.
- Short single-field = 12.5 / 10.25.
- Long multi-field = 88.625 / 16.875.
- Uncertainty / correction = 38.25 / 13.375.
- Cross-context = 46.5 / 12.6667.
