"""Step 3.4 - The Step 2 processor rebuilt on the reusable components.

Compared with step2_poc/claim_processor.py this version adds:
  * PII redaction before anything is sent to a model (ContentValidator.redact_pii)
  * schema validation of the extraction + one automatic "repair" retry
  * summary validation (structure, citations, grounding checks)
  * versioned prompt templates and per-call metrics/cost

  python step3_components/claim_pipeline.py claims/claim_002_home_water_damage.txt
  python step3_components/claim_pipeline.py --all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from step2_poc.claim_processor import load_document  # noqa: E402
from step2_poc.policy_rag import PolicyKnowledgeBase  # noqa: E402
from step2_poc.s3_storage import DocumentStore  # noqa: E402
from step3_components.content_validator import ContentValidator  # noqa: E402
from step3_components.model_invoker import ModelInvoker  # noqa: E402
from step3_components.prompt_manager import PromptTemplateManager  # noqa: E402


class ClaimPipeline:
    """The claim workflow assembled from the reusable components."""
    def __init__(self, store=None, kb=None, invoker=None, prompts=None, validator=None):
        self.store = store or DocumentStore()
        self.kb = kb or PolicyKnowledgeBase(self.store).build()
        self.invoker = invoker or ModelInvoker()
        self.prompts = prompts or PromptTemplateManager()
        self.validator = validator or ContentValidator()

    def extract(self, document_text: str, model_id: str, attachment=None) -> dict:
        """Extract and validate claim fields, with one repair retry if validation fails."""
        resp = self.invoker.invoke_template(self.prompts, "extract_info", model_id,
                                            document=attachment, document_text=document_text)
        calls = [resp]
        check = self.validator.validate_extraction(resp.text, source_text=document_text)
        if not check.valid:  # one repair attempt
            fix = self.invoker.invoke_template(self.prompts, "repair_json", model_id,
                                               errors="\n".join(check.errors), bad_output=resp.text)
            calls.append(fix)
            check = self.validator.validate_extraction(fix.text, source_text=document_text)
        return {"data": check.data, "validation": check.to_dict(), "calls": calls}

    def summarise(self, extracted: dict, model_id: str) -> dict:
        """Retrieve policy clauses and write a grounded summary, then validate it."""
        query = f"{extracted.get('claim_type')} claim: {extracted.get('incident_description')}"
        t0 = time.perf_counter()
        hits = self.kb.retrieve(query, extracted.get("policy_number"), k=4)
        retrieval_s = time.perf_counter() - t0
        resp = self.invoker.invoke_template(
            self.prompts, "generate_summary", model_id,
            extracted_info=json.dumps(extracted, indent=2),
            policy_context=self.kb.format_context(hits))
        check = self.validator.validate_summary(resp.text, extracted)
        return {"text": resp.text, "validation": check.to_dict(), "hits": hits, "calls": [resp],
                "retrieval_s": retrieval_s}

    def process(self, key: str, extraction_model: str = config.EXTRACTION_MODEL,
                summary_model: str = config.SUMMARY_MODEL, save: bool = True) -> dict:
        """Run the full pipeline for one document and return the result dict."""
        t_start = time.perf_counter()
        text, attachment = load_document(self.store, key)
        redacted, pii = self.validator.redact_pii(text)

        ext = self.extract(redacted, extraction_model, attachment)
        if ext["data"] is None:
            summ = {"text": "", "validation": {"valid": False, "errors": ["extraction failed"], "warnings": []},
                    "hits": [], "calls": [], "retrieval_s": 0.0}
        else:
            summ = self.summarise(ext["data"], summary_model)

        calls = ext["calls"] + summ["calls"]
        result = {
            "document": key,
            "redacted_text": redacted,
            "policy_context": self.kb.format_context(summ["hits"]),
            "pii_redacted": pii,
            "extracted_info": ext["data"],
            "extraction_validation": ext["validation"],
            "policy_sections_used": [f"{h['section']} {h['title']}" for h in summ["hits"]],
            "summary": summ["text"],
            "summary_validation": summ["validation"],
            "models": {"extraction": extraction_model, "summary": summary_model},
            "metrics": {
                "model_calls": len(calls),
                "repair_retries": len(ext["calls"]) - 1,
                "extraction_s": round(sum(c.latency_s for c in ext["calls"]), 3),
                "retrieval_s": round(summ["retrieval_s"], 3),
                "summary_s": round(sum(c.latency_s for c in summ["calls"]), 3),
                "total_s": round(time.perf_counter() - t_start, 3),
                "latency_s": round(sum(c.latency_s for c in calls), 2),
                "input_tokens": sum(c.input_tokens for c in calls),
                "output_tokens": sum(c.output_tokens for c in calls),
                "est_cost_usd": (round(sum(c.est_cost_usd for c in calls), 6)
                                 if all(c.est_cost_usd is not None for c in calls) else None),
            },
            "prompt_versions": {n: self.prompts.get(n).version for n in ("extract_info", "generate_summary")},
        }
        if save:
            result["saved_to"] = self.store.put_json(
                config.RESULTS_PREFIX + Path(key).stem + ".v2.json", result)
        return result


def main():
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", nargs="?")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    pipe = ClaimPipeline()
    keys = pipe.store.list_keys(config.CLAIMS_PREFIX) if a.all else [a.key]
    if keys == [None]:
        ap.error("give a key or --all")
    for key in keys:
        r = pipe.process(key)
        print("=" * 78, f"\n{key}\n" + "=" * 78)
        print("PII redacted:", r["pii_redacted"] or "none")
        print(json.dumps(r["extracted_info"], indent=2))
        print("Extraction validation:", json.dumps(r["extraction_validation"]))
        print("\n" + r["summary"])
        print("\nSummary validation:", json.dumps(r["summary_validation"]))
        print("Metrics:", r["metrics"], "\n")


if __name__ == "__main__":
    main()
