# A five-minute developer demo

Open the **Parallel queue**. Point out the 20 fictional Jira issues and enable
**Parallel requests** to start all selected tickets concurrently. Start the live batch
and watch multiple rows become active, then settle independently into routes, review
decisions, or incident escalation. The three
signals per issue are Choice for team ownership, Score for impact, and Noul for outage.

Read the actual completed count and elapsed time together: “This run completed X of
20 tickets in Y seconds.” Show successful tickets per second and estimated cost.
Throughput comes from this run. Cost uses successful input-token usage and published
pricing for the resolved model; output tokens are free. It is an estimate, not a bill.

To demonstrate the value of concurrency, uncheck **Parallel requests**, run the same
selection sequentially, and compare the measured batch durations. Do not promise a fixed
speedup or compare different ticket selections. Errors and rate limits stay visible and
reduce successful throughput.

Click an interesting ticket to inspect its three outputs. Then switch to **Single ticket**
and the production checkout outage. Before evaluating,
open the request inspector: one text state, one call, three atomic questions. Jev answers
each independently. The question names are lookup keys; the meaningful instructions
and descriptive criteria are visible in the payload.

Run the assessment. Walk across the three outputs: a team with competing probabilities,
customer impact positioned on the rubric, and a yes probability for active outage.
The incident outcome below is Python composing these answers into a policy.
The demo does not write to Jira or page an engineer.

Switch to the gateway/login ticket. It has genuine evidence for two teams. Discuss the
distribution rather than promising a particular model answer. Move the confidence
threshold: the policy is recomputed in Python using the existing response. The model
does not rerun, and no extra tokens are consumed. If this particular run yields an
extreme confidence, choose a different input rather than fabricating uncertainty.

Open **Reply verification**. Compare the support reply to the provided source policy.
Run the contradicted refund example, then the supported version. This illustrates
verification of supplied facts, not open-world fact checking or text generation.

Open **Runbook relevance**. Evaluate a useful mitigation and the irrelevant example.
Discuss how Python can evaluate a shortlist of candidate pairs and sort the resulting
scores. The current demo evaluates one pair at a time; it is not a search engine.

Finish in the Python inspector. The API key comes from an environment variable, model
answers are validated, and the routing decisions are ordinary code. The same typed
answers can feed a queue, review interface, or a larger application.

## Extensions worth building next

| Use case | Useful interaction | Jev capability |
| --- | --- | --- |
| Backlog prioritization | Score impact, urgency, and report completeness separately; change Python weights without rerunning the model | [Composite Scores](https://docs.typesafe.ai/patterns/composite-scoring) |
| Runbook re-ranking | Evaluate a fixed shortlist against an incident and sort candidates in Python | [Semantic re-ranking](https://docs.typesafe.ai/cookbooks/rerank_typesafe) |
| Automation preflight | Inspect separate checks for personal data, unsupported promises, and instruction overrides; route uncertain actions for review | [Multiple Noul guardrails](https://docs.typesafe.ai/cookbooks/llm_guardrails) |
| Extraction quality gate | Compare already-extracted order fields against source text and flag unsupported values | [Verification cascade](https://docs.typesafe.ai/cookbooks/sde_cascade) |
| Hierarchical issue taxonomy | Choose project, component, and subcomponent while retaining plausible alternative paths | [Hierarchical classification](https://docs.typesafe.ai/primitives/choice) |

These are proposals, not capabilities implemented behind inactive controls. Free-form
extraction or response writing would require a separate generator; Jev supplies decisions.
For image-based extraction, Jev needs independent source text from OCR or another
trusted text source to check factual support. Without that evidence, a text-only check
can assess consistency but cannot verify that a field matches the image; use a vision
verifier for that comparison.

## Presentation discipline

Use live observed latency and token counts, and show failures honestly. A confidence
value of 1 does not guarantee correctness. Strong claims about calibration or business
performance need a labeled evaluation set and a pinned model version. The fictional
examples are useful for explanation, not an accuracy benchmark.
