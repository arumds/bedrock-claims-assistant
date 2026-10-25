"""Step 2.5 - Proof-of-concept claim processor (Bedrock integration + RAG + summary).

Workflow for one claim document in S3:
  1. read the document from S3
  2. extract structured fields with the extraction model (temperature 0)
  3. retrieve relevant policy clauses (RAG) using the incident description
  4. generate a grounded claim summary with the summary model
  5. save the result JSON back to S3 under results/

This file deliberately keeps prompts inline and calls boto3 directly, so you
can see exactly what is sent to Bedrock. Step 3 refactors this into reusable
components.

  python step2_poc/claim_processor.py claims/claim_001_auto_collision.txt
  python step2_poc/claim_processor.py --all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import mock_bedrock  # noqa: E402
from step2_poc.policy_rag import PolicyKnowledgeBase  # noqa: E402
from step2_poc.s3_storage import DocumentStore  # noqa: E402

_bedrock = None


def converse(model_id: str, prompt: str, system: str, temperature: float, max_tokens: int,
             document: dict | None = None) -> tuple[str, dict]:
    """One Bedrock Converse call. Returns (text, metrics)."""
    if config.MOCK_MODE:
        r = mock_bedrock.mock_converse(model_id, prompt, system)
        return r.text, {"latency_s": r.latency_s, "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens}
    global _bedrock
    if _bedrock is None:
        import boto3
        _bedrock = boto3.client("bedrock-runtime", region_name=config.REGION)
    content = ([{"document": document}] if document else []) + [{"text": prompt}]
    start = time.perf_counter()
    resp = _bedrock.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
    )
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    usage = resp.get("usage", {})
    return text.strip(), {"latency_s": round(time.perf_counter() - start, 2),
                          "input_tokens": usage.get("inputTokens", 0),
                          "output_tokens": usage.get("outputTokens", 0)}


def load_document(store: DocumentStore, key: str) -> tuple[str, dict | None]:
    """Text files are inlined; PDFs/DOCX are sent as a Converse document block
    so the model does the document understanding (layout, tables)."""
    data = store.get_bytes(key)
    ext = Path(key).suffix.lower().lstrip(".")
    if ext in ("txt", "md", "csv", "html"):
        return data.decode("utf-8", errors="replace"), None
    name = re.sub(r"[^A-Za-z0-9\-]", "-", Path(key).stem)[:100]
    return "(see attached document)", {"name": name, "format": ext, "source": {"bytes": data}}


def parse_json(text: str) -> dict:
    """Parse the JSON object out of a model reply (tolerates ``` fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


EXTRACT_SYSTEM = ("You are an insurance claims intake specialist. Extract facts exactly as "
                  "written. Use null for anything not in the document. Reply with JSON only.")
EXTRACT_PROMPT = """Extract these fields from the claim document and return a JSON object:
claimant_name, policy_number, claim_type (auto|home|health|other),
incident_date (YYYY-MM-DD), claim_amount (number), currency, incident_location,
incident_description (1-3 sentences), supporting_documents (list).

<document>
{document_text}
</document>"""

SUMMARY_SYSTEM = ("You are a senior claims adjuster. Use ONLY the claim data and policy "
                  "excerpts given. Cite sections like [Section 2.1]. If coverage is unclear, say so.")
SUMMARY_PROMPT = """Extracted claim data:
{extracted_info}

Relevant policy excerpts (retrieved from the policy knowledge base):
{policy_context}

Write: **Claim overview** (2-3 sentences), **Coverage assessment** (Likely covered / Likely not
covered / Needs review, with citations), **Deductible & limits**, **Missing information**,
**Recommended next step**."""


def process_document(key: str, store: DocumentStore | None = None,
                     kb: PolicyKnowledgeBase | None = None,
                     extraction_model: str = config.EXTRACTION_MODEL,
                     summary_model: str = config.SUMMARY_MODEL) -> dict:
    """Run the whole Step 2 workflow for one S3 document and save the result."""
    store = store or DocumentStore()
    kb = kb or PolicyKnowledgeBase(store).build()

    # 1. Read document
    document_text, attachment = load_document(store, key)

    # 2. Information extraction
    raw, m1 = converse(extraction_model, EXTRACT_PROMPT.format(document_text=document_text),
                       EXTRACT_SYSTEM, temperature=0.0, max_tokens=1000, document=attachment)
    extracted = parse_json(raw)

    # 3. RAG: retrieve policy clauses relevant to this incident
    query = f"{extracted.get('claim_type')} claim: {extracted.get('incident_description')}"
    hits = kb.retrieve(query, extracted.get("policy_number"), k=4)

    # 4. Summary generation grounded in extracted data + policy clauses
    summary, m2 = converse(summary_model,
                           SUMMARY_PROMPT.format(extracted_info=json.dumps(extracted, indent=2),
                                                 policy_context=kb.format_context(hits)),
                           SUMMARY_SYSTEM, temperature=0.3, max_tokens=600)

    result = {
        "document": key,
        "extracted_info": extracted,
        "policy_sections_used": [f"{h['section']} {h['title']}" for h in hits],
        "summary": summary,
        "models": {"extraction": extraction_model, "summary": summary_model},
        "metrics": {"extraction": m1, "summary": m2},
    }
    # 5. Save response
    result["saved_to"] = store.put_json(config.RESULTS_PREFIX + Path(key).stem + ".json", result)
    return result


def main():
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", nargs="?", help="S3 key, e.g. claims/claim_001_auto_collision.txt")
    ap.add_argument("--all", action="store_true", help="process every document under claims/")
    a = ap.parse_args()
    store = DocumentStore()
    kb = PolicyKnowledgeBase(store).build()
    keys = store.list_keys(config.CLAIMS_PREFIX) if a.all else [a.key]
    if not keys or keys == [None]:
        ap.error("give a key or --all")
    for key in keys:
        r = process_document(key, store, kb)
        print("=" * 78, f"\n{key}\n" + "=" * 78)
        print(json.dumps(r["extracted_info"], indent=2))
        print("\nPolicy sections retrieved:", ", ".join(r["policy_sections_used"]))
        print("\n" + r["summary"])
        print(f"\nsaved -> {r['saved_to']}\n")


if __name__ == "__main__":
    main()
