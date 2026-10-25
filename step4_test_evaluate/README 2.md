# Step 4 – Test and evaluate

## 4.1 Sample documents

`sample_data/claims/` has three claims, each built to test something different:

| Document | Type | What it tests | Expected verdict |
|---|---|---|---|
| `claim_001_auto_collision.txt` | Auto | Clean, well-structured form; third party at fault | Likely covered (deductible waived, §1.3) |
| `claim_002_home_water_damage.txt` | Home | Contains **SSN + IBAN**; slow leak over weeks | Likely **not** covered (gradual-leak exclusion, §2.2) |
| `claim_003_health_er_visit.txt` | Health | Date written as "3 March 2026" (needs normalising); out-of-network ER | Likely covered (emergency, §3.1–3.2) |

The expected values are in `sample_data/ground_truth.json`. Add your own documents (PDFs work too) with `step2_poc/upload_documents.py`, and add their expected values to that file to include them in scoring.

## 4.2 Run the processor on all documents

```bash
python step2_poc/upload_documents.py          # if you haven't already
python step3_components/claim_pipeline.py --all
```

## 4.3 Compare models

```bash
python step4_test_evaluate/compare_models.py
# or choose your own models:
python step4_test_evaluate/compare_models.py --models eu.amazon.nova-lite-v1:0,eu.amazon.nova-pro-v1:0
```

Each model runs the **full pipeline** (extraction and summary) on every document and is scored on:

| Metric | How |
|---|---|
| Field accuracy | 6 fields compared with the ground truth (name, policy number, type, date, amount, currency) |
| Coverage verdict accuracy | "Likely covered / not covered / Needs review" in the summary compared with the expected verdict |
| Citations | distinct `[Section x.y]` references in the summary |
| Summary warnings | from `ContentValidator.validate_summary` |
| Latency, tokens, cost | from `ModelResponse` metrics |

Models you don't have access to are **skipped and listed** in the report; the run doesn't fail.

Outputs in `step4_test_evaluate/results/`:
- `comparison_report.md` – summary table, per-document detail and an automatic recommendation
- `comparison.csv` – raw numbers for your own charts
- `<model>__<document>.json` – full outputs, so you can read and compare the summaries yourself

> In `MOCK_MODE` the numbers are meaningless; every "model" is the same regex. Run with real Bedrock for your findings.

## 4.4 Document your findings

Fill in [`FINDINGS.md`](FINDINGS.md) using the report. It's already structured with the questions to answer.

➡ Optional: [Extras – web UI, feedback, cleanup](../extras/README.md)
