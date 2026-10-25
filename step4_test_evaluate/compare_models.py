"""Step 4 - Test, compare models and evaluate the solution on four criteria.

  1. Accuracy of information extraction   field-level accuracy vs ground truth
  2. Quality of generated summaries        coverage verdict, key-fact recall, retrieval
                                           recall, validator checks, LLM-as-a-judge rubric
  3. Processing time and efficiency        per-stage latency, tokens, cost, retries, throughput
  4. Code organisation and reusability     static analysis (code_quality.py)

Every model in COMPARE_MODELS runs the full Step 3 pipeline (extraction + summary)
on every sample document. Models you can't access are skipped and listed.

Outputs in step4_test_evaluate/results/:
  evaluation_report.md     the four-criteria report + recommendation
  comparison.csv           one row per model x document (raw numbers)
  code_quality_report.md   criterion 4 in full
  <model>__<doc>.json      full pipeline output, for reading summaries side by side

  python step4_test_evaluate/compare_models.py
  python step4_test_evaluate/compare_models.py --models eu.amazon.nova-lite-v1:0,eu.amazon.nova-pro-v1:0
  python step4_test_evaluate/compare_models.py --no-judge      # skip LLM-as-a-judge calls
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from step3_components.claim_pipeline import ClaimPipeline  # noqa: E402
from step4_test_evaluate import code_quality  # noqa: E402

FIELDS = ["claimant_name", "policy_number", "claim_type", "incident_date", "claim_amount", "currency"]
VERDICTS = ["likely not covered", "likely covered", "needs review"]  # "not covered" checked first
JUDGE_CRITERIA = ["faithfulness", "completeness", "coverage_reasoning", "clarity"]


# ------------------------------------------------------------ criterion 1
def field_correct(field: str, got, expected) -> bool:
    """Compare one extracted field with the expected value (amounts to the cent)."""
    if got is None:
        return expected is None
    if field == "claim_amount":
        try:
            return abs(float(got) - float(expected)) < 0.01
        except (TypeError, ValueError):
            return False
    return str(got).strip().lower() == str(expected).strip().lower()


def score_extraction(result: dict, truth: dict) -> dict:
    """Per-field correctness plus overall accuracy for one document."""
    ext = result.get("extracted_info") or {}
    per_field = {f: field_correct(f, ext.get(f), truth.get(f)) for f in FIELDS}
    return {
        **{f"ok_{f}": ok for f, ok in per_field.items()},
        "field_accuracy": sum(per_field.values()) / len(FIELDS),
        "wrong_fields": ";".join(f for f, ok in per_field.items() if not ok),
        "extraction_valid": result["extraction_validation"]["valid"],
        "extraction_warnings": len(result["extraction_validation"]["warnings"]),
    }


# ------------------------------------------------------------ criterion 2
def verdict_of(summary: str) -> str | None:
    """Pull the coverage verdict out of the summary's 'Coverage assessment' line."""
    m = re.search(r"coverage assessment[:*\s]*([^\n]*)", summary, re.I)
    line = (m.group(1) if m else summary).lower()
    return next((v for v in VERDICTS if v in line), None)


def key_fact_recall(summary: str, facts: list[dict]) -> tuple[float, list[str]]:
    """Share of expected key facts the summary mentions (keyword match per fact)."""
    low = summary.lower()
    missed = [f["fact"] for f in facts if not any(k.lower() in low for k in f["any_of"])]
    return (1 - len(missed) / len(facts) if facts else 1.0), missed


def retrieval_recall(result: dict, expected_sections: list[str]) -> float:
    """Share of the policy sections needed for this claim that RAG retrieved."""
    got = {m for s in result.get("policy_sections_used", []) for m in re.findall(r"Section ([\d.]+)", s)}
    return len(got & set(expected_sections)) / len(expected_sections) if expected_sections else 1.0


def judge_summary(pipe: ClaimPipeline, result: dict, judge_model: str) -> dict:
    """LLM-as-a-judge: score the summary 1-5 on the rubric in the judge_summary template."""
    try:
        resp = pipe.invoker.invoke_template(
            pipe.prompts, "judge_summary", judge_model,
            document_text=result["redacted_text"], policy_context=result["policy_context"],
            summary=result["summary"])
        scores = pipe.validator.parse_json_output(resp.text)
        out = {f"judge_{c}": float(scores.get(c, 0)) for c in JUDGE_CRITERIA}
        out["judge_avg"] = statistics.mean(out.values())
        out["judge_issues"] = "; ".join(scores.get("issues", []))[:300]
        return out
    except Exception as e:  # judge failure must not break the evaluation
        return {"judge_avg": None, "judge_issues": f"judge failed: {type(e).__name__}"}


def score_summary(result: dict, truth: dict) -> dict:
    """Rule-based summary metrics for one document."""
    summary = result.get("summary", "")
    verdict = verdict_of(summary)
    recall, missed = key_fact_recall(summary, truth.get("key_facts", []))
    return {
        "verdict": verdict or "",
        "verdict_correct": verdict == truth.get("expected_coverage", "").lower(),
        "key_fact_recall": recall,
        "missed_facts": "; ".join(missed),
        "retrieval_recall": retrieval_recall(result, truth.get("expected_sections", [])),
        "citations": len(set(re.findall(r"\[Section [\d.]+\]", summary))),
        "summary_valid": result["summary_validation"]["valid"],
        "summary_warnings": len(result["summary_validation"]["warnings"]),
        "summary_words": len(summary.split()),
    }


# ------------------------------------------------------------ run
def run_model(pipe: ClaimPipeline, model: str, keys: list[str], truth: dict,
              judge_model: str | None, out_dir: Path) -> list[dict]:
    """Process every document with one model; return one scored row per document."""
    rows = []
    for key in keys:
        name = Path(key).name
        r = pipe.process(key, extraction_model=model, summary_model=model, save=False)
        row = {"model": model, "document": name,
               **score_extraction(r, truth[name]), **score_summary(r, truth[name]), **r["metrics"]}
        if judge_model:
            row.update(judge_summary(pipe, r, judge_model))
        rows.append(row)
        safe = re.sub(r"[^\w.-]", "_", model)
        (out_dir / f"{safe}__{Path(name).stem}.json").write_text(json.dumps(r, indent=2, default=str))
        judge = f" judge {row['judge_avg']:.1f}/5" if row.get("judge_avg") is not None else ""
        print(f"   {name:36s} fields {row['field_accuracy']:.0%}  verdict={row['verdict'] or '?':18s}"
              f" facts {row['key_fact_recall']:.0%}{judge}  {row['total_s']:.2f}s")
    return rows


def _mean(rows: list[dict], key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.mean(float(v) for v in vals) if vals else None


def aggregate(rows: list[dict]) -> list[dict]:
    """Average each metric per model."""
    agg = []
    for model in dict.fromkeys(r["model"] for r in rows):
        rs = [r for r in rows if r["model"] == model]
        a = {"model": model, "n": len(rs)}
        for k in (["field_accuracy", "verdict_correct", "key_fact_recall", "retrieval_recall",
                   "citations", "summary_warnings", "extraction_warnings", "judge_avg",
                   "extraction_s", "retrieval_s", "summary_s", "total_s", "repair_retries",
                   "input_tokens", "output_tokens", "est_cost_usd"]
                  + [f"ok_{f}" for f in FIELDS] + [f"judge_{c}" for c in JUDGE_CRITERIA]):
            a[k] = _mean(rs, k)
        a["max_total_s"] = max(r["total_s"] for r in rs)
        parts = [a["verdict_correct"], a["key_fact_recall"]]
        if a["judge_avg"] is not None:
            parts.append(a["judge_avg"] / 5)
        a["summary_score"] = statistics.mean(parts)
        agg.append(a)
    return agg


# ------------------------------------------------------------ report
def pct(v) -> str:
    """Format a 0-1 value as a percentage, or n/a."""
    return "n/a" if v is None else f"{v:.0%}"


def num(v, fmt: str = ".2f") -> str:
    """Format a number, or n/a."""
    return "n/a" if v is None else format(v, fmt)


def recommend(agg: list[dict]) -> dict:
    """Pick the best model per task from the aggregated metrics."""
    def _cost(a):
        return a["est_cost_usd"] if a["est_cost_usd"] is not None else float("inf")
    best_ext = max(agg, key=lambda a: (round(a["field_accuracy"], 3), -_cost(a)))
    best_sum = max(agg, key=lambda a: (round(a["summary_score"], 3), -_cost(a)))
    good = [a for a in agg if a["field_accuracy"] >= best_ext["field_accuracy"] - 0.05
            and a["summary_score"] >= best_sum["summary_score"] - 0.1]
    value = min(good or agg, key=_cost)
    fastest = min(agg, key=lambda a: a["total_s"])
    return {"extraction": best_ext, "summary": best_sum, "value": value, "fastest": fastest}


def section_accuracy(agg, rows) -> list[str]:
    """Markdown for criterion 1."""
    lines = ["## 1. Accuracy of information extraction", "",
             "Six fields compared with `sample_data/ground_truth.json` (amount to the cent, text case-insensitive).", "",
             "| Model | Overall | " + " | ".join(FIELDS) + " | Validator warnings / doc |",
             "|---|---|" + "---|" * len(FIELDS) + "---|"]
    for a in agg:
        lines.append(f"| `{a['model']}` | **{pct(a['field_accuracy'])}** | "
                     + " | ".join(pct(a[f'ok_{f}']) for f in FIELDS)
                     + f" | {num(a['extraction_warnings'], '.1f')} |")
    errors = [r for r in rows if r["wrong_fields"]]
    if errors:
        lines += ["", "Errors: " + "; ".join(f"`{r['model']}` / {r['document']}: {r['wrong_fields']}" for r in errors)]
    return lines


def section_summary(agg, rows, judge_model) -> list[str]:
    """Markdown for criterion 2."""
    lines = ["", "## 2. Quality of generated summaries", "",
             "- **Verdict accuracy**: coverage verdict matches the expected one",
             "- **Key-fact recall**: the summary mentions the policy facts an adjuster needs (4 per claim)",
             "- **Retrieval recall**: RAG returned the policy sections needed (limits what any model can get right)",
             f"- **Judge**: LLM-as-a-judge rubric, 1–5, by `{judge_model or 'disabled'}`",
             "- **Summary score** = mean(verdict accuracy, key-fact recall, judge/5)", "",
             "| Model | Summary score | Verdict acc. | Key-fact recall | Retrieval recall | Citations | "
             + " | ".join(c.replace("_", " ").title() for c in JUDGE_CRITERIA) + " | Validator warnings / doc |",
             "|---|---|---|---|---|---|" + "---|" * len(JUDGE_CRITERIA) + "---|"]
    for a in agg:
        lines.append(f"| `{a['model']}` | **{pct(a['summary_score'])}** | {pct(a['verdict_correct'])} | "
                     f"{pct(a['key_fact_recall'])} | {pct(a['retrieval_recall'])} | {num(a['citations'], '.1f')} | "
                     + " | ".join(num(a[f'judge_{c}'], '.1f') for c in JUDGE_CRITERIA)
                     + f" | {num(a['summary_warnings'], '.1f')} |")
    lines += ["", "| Model | Document | Verdict | Correct | Missed facts | Judge issues |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| `{r['model']}` | {r['document']} | {r['verdict'] or '?'} | "
                     f"{'✅' if r['verdict_correct'] else '❌'} | {r['missed_facts'] or '—'} | "
                     f"{r.get('judge_issues') or '—'} |")
    return lines


def section_efficiency(agg) -> list[str]:
    """Markdown for criterion 3."""
    lines = ["", "## 3. Processing time and efficiency", "",
             "Per claim, sequential processing. Judge calls are excluded.", "",
             "| Model | Extraction (s) | Retrieval (s) | Summary (s) | Total avg (s) | Total max (s) | "
             "Claims / min | Tokens in / out | Repair retries | Cost / claim | Cost / 1,000 claims |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in agg:
        c = a["est_cost_usd"]
        lines.append(
            f"| `{a['model']}` | {num(a['extraction_s'])} | {num(a['retrieval_s'])} | {num(a['summary_s'])} | "
            f"**{num(a['total_s'])}** | {num(a['max_total_s'])} | {num(60 / a['total_s'] if a['total_s'] else None, '.1f')} | "
            f"{num(a['input_tokens'], '.0f')} / {num(a['output_tokens'], '.0f')} | {num(a['repair_retries'], '.1f')} | "
            f"{'n/a' if c is None else f'${c:.5f}'} | {'n/a' if c is None else f'${c * 1000:.2f}'} |")
    return lines


def build_report(agg, rows, failures, cq, judge_model, n_docs) -> str:
    """Assemble the full four-criteria evaluation report."""
    rec = recommend(agg)
    mode = "**MOCK MODE: synthetic numbers, not real model results**" if config.MOCK_MODE else "live Amazon Bedrock"
    lines = ["# Solution evaluation report", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M} · region `{config.REGION}` · {mode} · "
             f"{n_docs} documents · {len(agg)} models", "",
             "## Scorecard (recommended configuration)", "",
             "| Criterion | Result |", "|---|---|",
             f"| 1. Extraction accuracy | {pct(rec['extraction']['field_accuracy'])} with `{rec['extraction']['model']}` |",
             f"| 2. Summary quality | {pct(rec['summary']['summary_score'])} summary score with `{rec['summary']['model']}` |",
             f"| 3. Time & efficiency | {num(rec['value']['total_s'])} s and "
             f"{'n/a' if rec['value']['est_cost_usd'] is None else '$%.5f' % rec['value']['est_cost_usd']} per claim "
             f"with `{rec['value']['model']}` (fastest: `{rec['fastest']['model']}`, {num(rec['fastest']['total_s'])} s) |",
             f"| 4. Code organisation | {cq['score']}/{len(cq['checks'])} checks passed · {cq['tests'][2]} |", ""]
    lines += section_accuracy(agg, rows)
    lines += section_summary(agg, rows, judge_model)
    lines += section_efficiency(agg)
    lines += ["", code_quality.markdown(cq, heading_level=2).replace(
        "## Code organisation and reusability", "## 4. Code organisation and reusability", 1)]
    if failures:
        lines += ["## Skipped models", ""] + [f"- `{m}`: {e}" for m, e in failures.items()] + [""]
    lines += ["## Recommendation", "",
              f"- **Document understanding / extraction:** `{rec['extraction']['model']}`",
              f"- **Summary generation:** `{rec['summary']['model']}`",
              f"- **Best value (within 5 pts accuracy and 10 pts summary score of the best):** `{rec['value']['model']}`",
              "", "Read the per-model JSON files to check the summaries yourself, then write up `FINDINGS.md`."]
    return "\n".join(lines) + "\n"


def main():
    """Run all models on all documents, then write the CSV and the report."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", help="comma-separated model IDs (default: config.COMPARE_MODELS)")
    ap.add_argument("--judge-model", default=config.JUDGE_MODEL)
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM-as-a-judge calls")
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",")] if a.models else config.COMPARE_MODELS
    judge_model = None if a.no_judge else a.judge_model

    truth = json.loads((config.SAMPLE_DIR / "ground_truth.json").read_text())
    out = config.RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    pipe = ClaimPipeline()
    keys = [k for k in pipe.store.list_keys(config.CLAIMS_PREFIX) if Path(k).name in truth]
    if not keys:
        sys.exit("No sample claims in storage. Run step2_poc/upload_documents.py first.")

    rows, failures = [], {}
    for model in models:
        print(f"\n### {model}")
        try:
            rows += run_model(pipe, model, keys, truth, judge_model, out)
        except Exception as e:  # access denied, model not in region, ...
            failures[model] = f"{type(e).__name__}: {str(e)[:160]}"
            print(f"   SKIPPED: {failures[model]}")
            rows = [r for r in rows if r["model"] != model]
    if not rows:
        sys.exit("No model produced results. Check model access in the Bedrock console.")

    with open(out / "comparison.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        w.writerows(rows)

    print("\nAnalysing code quality ...")
    cq = code_quality.evaluate()
    (out / "code_quality_report.md").write_text(code_quality.markdown(cq))
    report = build_report(aggregate(rows), rows, failures, cq, judge_model, len(keys))
    (out / "evaluation_report.md").write_text(report)
    print(report.split("## 1.")[0])
    print(f"Full report: {out / 'evaluation_report.md'}")


if __name__ == "__main__":
    main()
