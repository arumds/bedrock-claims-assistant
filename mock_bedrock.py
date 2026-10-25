"""Offline stand-in for Amazon Bedrock (MOCK_MODE=1).

Lets you run every step of the assignment with zero AWS cost: a regex-driven
"model" that returns realistic JSON / summaries, and a hashed bag-of-words
embedding. Results are NOT real model quality - use real Bedrock for Step 4.
"""
from __future__ import annotations

import json
import math
import re
import time
import zlib
from dataclasses import dataclass


@dataclass
class MockResult:
    """What the fake model returns: text plus latency and token counts."""
    text: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    stop_reason: str = "end_turn"


def mock_embedding(text: str, dims: int = 256) -> list[float]:
    """Hashed bag-of-words vector: similar texts -> similar vectors."""
    vec = [0.0] * dims
    for tok in re.findall(r"[a-z]{3,}", text.lower()):
        vec[zlib.crc32(tok.encode()) % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _find(pattern: str, text: str):
    m = re.search(pattern, text, re.I | re.M)
    return m.group(1).strip() if m else None


def mock_converse(model_id: str, prompt: str, system: str | None = None) -> MockResult:
    """Deterministic stand-in for a model, driven by regexes over the prompt."""
    time.sleep(0.01)
    if "Rate the summary" in prompt:
        summ = prompt.split("<summary>", 1)[1]
        cited = len(set(re.findall(r"\[Section [\d.]+\]", summ)))
        text = json.dumps({"faithfulness": 4, "completeness": 3,
                           "coverage_reasoning": 2 + min(cited, 2), "clarity": 4,
                           "issues": ["[MOCK] scores are synthetic"]})
    elif "<document>" in prompt:
        doc = prompt.split("<document>", 1)[1].split("</document>", 1)[0]
        amount = _find(r"(?:amount claimed|claim amount|total claimed)[^\d]*([\d,]+(?:\.\d+)?)", doc)
        lower = doc.lower()
        ctype = ("auto" if any(w in lower for w in ("vehicle", "collision", "car "))
                 else "home" if any(w in lower for w in ("water", "roof", "property", "home"))
                 else "health" if any(w in lower for w in ("hospital", "medical", "patient"))
                 else "other")
        data = {
            "claimant_name": _find(r"(?:claimant|insured|policyholder|patient)(?: name)?\s*:\s*(.+)", doc),
            "policy_number": _find(r"policy (?:number|no\.?)\s*:\s*([A-Z0-9\-]+)", doc),
            "claim_type": ctype,
            "incident_date": _find(r"(?:date of (?:incident|loss|service|admission)|incident date)\s*:\s*(\d{4}-\d{2}-\d{2})", doc),
            "claim_amount": float(amount.replace(",", "")) if amount else None,
            "currency": _find(r"\b(USD|EUR|GBP)\b", doc),
            "incident_location": _find(r"location\s*:\s*(.+)", doc),
            "incident_description": (_find(r"description[^:]*:\s*\n?(.+)", doc) or "")[:300] or None,
            "supporting_documents": [],
        }
        text = json.dumps(data, indent=2)
    elif "corrected JSON" in prompt:
        text = prompt.split("Original output:", 1)[1].split("Return a corrected", 1)[0].strip()
    elif "Extracted claim data" in prompt:
        data_part = prompt.split("Extracted claim data:", 1)[1].split("Relevant policy", 1)[0]
        sections = re.findall(r"\[(Section [\d.]+)\]", prompt)
        try:
            d = json.loads(data_part)
        except json.JSONDecodeError:
            d = {}
        text = (
            f"**Claim overview:** {d.get('claimant_name')} filed a {d.get('claim_type')} claim "
            f"under policy {d.get('policy_number')} for an incident on {d.get('incident_date')}, "
            f"claiming {d.get('claim_amount')} {d.get('currency') or ''}.\n"
            f"**Coverage assessment:** Needs review - [MOCK] see "
            f"{', '.join('[' + s + ']' for s in sections[:2]) or 'no excerpts found'}.\n"
            "**Deductible & limits:** See cited sections.\n"
            "**Missing information:** None\n"
            "**Recommended next step:** Assign to an adjuster for verification."
        )
    else:
        text = "[MOCK] " + prompt[:200]
    in_tok = len(prompt) // 4 + len(system or "") // 4
    return MockResult(text=text, latency_s=0.01, input_tokens=in_tok,
                      output_tokens=len(text) // 4)
