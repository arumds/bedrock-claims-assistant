# Step 4 – Test and evaluate

One command tests the sample documents, compares the models and evaluates the solution on the four assignment criteria:

```bash
python step2_poc/upload_documents.py              # if you haven't already
python step4_test_evaluate/compare_models.py
```

Options: `--models id1,id2` to choose models · `--judge-model <id>` to set the judge · `--no-judge` to skip judge calls.

## 4.1 Sample documents

| Document | Type | What it tests | Expected verdict |
|---|---|---|---|
| `claim_001_auto_collision.txt` | Auto | Clean form; third party at fault | Likely covered (deductible waived, §1.3) |
| `claim_002_home_water_damage.txt` | Home | Contains **SSN + IBAN**; slow leak over weeks | Likely **not** covered (gradual leakage, §2.2) |
| `claim_003_health_er_visit.txt` | Health | Date written "3 March 2026"; out-of-network ER | Likely covered (emergency, §3.1–3.2) |

`sample_data/ground_truth.json` holds the expected fields, verdict, **key facts** and **policy sections** for each claim. To include your own documents in scoring, upload them and add an entry there.

## 4.2 How each criterion is measured

| Criterion | Metrics | Where in the code |
|---|---|---|
| **1. Accuracy of information extraction** | Accuracy for each of the 6 fields vs ground truth · overall field accuracy · validator warnings (hallucination and format) | `score_extraction()` |
| **2. Quality of generated summaries** | **Verdict accuracy** (covered / not covered / needs review) · **key-fact recall** (does the summary state the 4 policy facts an adjuster needs?) · **retrieval recall** (did RAG return the right sections?) · citations · validator checks · **LLM-as-a-judge** 1–5 scores for faithfulness, completeness, coverage reasoning and clarity → combined **summary score** | `score_summary()`, `judge_summary()`, the `judge_summary` prompt template |
| **3. Processing time and efficiency** | Latency **per stage** (extraction, retrieval, summary) · average and max total per claim · claims per minute · input/output tokens · repair retries · cost per claim and per 1,000 claims | `ClaimPipeline.process()` metrics, `section_efficiency()` |
| **4. Code organisation and reusability** | Static analysis: reuse map (which files import each component) · no hard-coded model IDs · module size · function length · docstring and type-hint coverage · unit tests pass | `code_quality.py` (also runs on its own) |

**About the LLM judge:** a model scoring summaries is useful but imperfect. It can favour its own style, so set `--judge-model` to a model you are *not* comparing if you can (for example a Claude Sonnet model). The rule-based metrics (verdict, key facts, retrieval) don't depend on the judge, which is why the summary score combines both.

## 4.3 Outputs (`step4_test_evaluate/results/`)

| File | Contents |
|---|---|
| `evaluation_report.md` | **Main report.** Scorecard, then one section per criterion, then the recommendation |
| `comparison.csv` | Every metric, one row per model × document, for your own charts |
| `code_quality_report.md` | Criterion 4 in full (also produced by `python step4_test_evaluate/code_quality.py`) |
| `<model>__<doc>.json` | Full pipeline output; read the summaries side by side |

> In `MOCK_MODE` all "models" are the same regex, so the numbers only show that the evaluation works. Run against real Bedrock for your findings. Criterion 4 is the same in both modes.

## 4.4 Document your findings

Fill in [`FINDINGS.md`](FINDINGS.md). It's laid out by the same four criteria, with questions to answer under each.

➡ Optional: [Extras – web UI, feedback, cleanup](../extras/README.md)
