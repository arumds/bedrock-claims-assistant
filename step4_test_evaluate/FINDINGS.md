# Findings and recommendations

> Fill this in after running `python step4_test_evaluate/compare_models.py` against real Bedrock.
> Every number you need is in `results/evaluation_report.md`.

**Date:** ____  **Region:** ____  **Documents:** 3  **Models compared:** ____  **Judge model:** ____

## Scorecard

| Criterion | Result | Verdict (✅ / ⚠️ / ❌) |
|---|---|---|
| 1. Accuracy of information extraction | __% field accuracy (best model: ____) | |
| 2. Quality of generated summaries | __% summary score · __% verdict accuracy · __% key-fact recall | |
| 3. Processing time and efficiency | __ s/claim · $____ per 1,000 claims | |
| 4. Code organisation and reusability | __/9 checks · __ tests passing | |

---

## 1. Accuracy of information extraction

| Model | Overall | Weakest field | Notes |
|---|---|---|---|
| | | | |

- Which models normalised "3 March 2026" to `2026-03-03` (claim 003)?
- Did any model return the amount as a string or with a currency symbol? (validator warnings)
- Any hallucination warnings (values not found in the document)? Did the repair retry ever trigger?

## 2. Quality of generated summaries

| Model | Summary score | Verdict acc. | Key-fact recall | Judge avg | Notes |
|---|---|---|---|---|---|
| | | | | | |

- **Claim 002 is the hardest test:** did the model apply the gradual-leakage exclusion (§2.2), or call the claim covered?
- **Retrieval recall:** was a missed fact caused by RAG not retrieving the section (a retrieval problem) or by the model ignoring it (a generation problem)?
- Do the judge scores agree with your own reading of the summaries? Note any disagreement.

## 3. Processing time and efficiency

| Model | Extraction (s) | Summary (s) | Total (s) | Tokens / claim | Cost / 1,000 claims |
|---|---|---|---|---|---|
| | | | | | |

- Which stage dominates latency? Is retrieval negligible?
- Is the most accurate model worth its extra cost and latency at your expected volume?
- Any throttling or retries?

## 4. Code organisation and reusability

- Score: __/9 (see `results/code_quality_report.md`)
- How the components were reused: the same `ClaimPipeline` serves the CLI, the web app, the tests and this evaluation; swapping models needed **no code changes**, only model IDs.
- What I would refactor next: ____

---

## Recommendations

| Task | Recommended model | Reason (cite the metrics) |
|---|---|---|
| Document understanding / extraction | | |
| Summary generation | | |

**Improvements for production**
1. Retrieval: raise `k`, or use Bedrock Knowledge Bases with hybrid search, if retrieval recall is below 100%.
2. Add Bedrock Guardrails (PII filters, contextual grounding check) as well as the regex filter.
3. Orchestrate with Step Functions, triggered by an S3 event; process claims in parallel for throughput.
4. Build a larger labelled test set (20+ claims, including scanned PDFs) and run Bedrock model evaluation jobs.
5. Feed 👎 feedback back into prompt versions (`prompt_versions` is already logged with each result).

## What I learned
- 
