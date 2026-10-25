"""Reusable component #3 - Content validator.

* parse_json_output: robustly pull a JSON object out of model text
* validate_extraction: schema / type / format / plausibility checks
* validate_summary: structure + grounding checks against the extracted data
* redact_pii: content filter for sensitive information (extension task)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

REQUIRED_FIELDS = ["claimant_name", "policy_number", "incident_date",
                   "claim_amount", "incident_description"]
OPTIONAL_FIELDS = ["claim_type", "currency", "incident_location", "supporting_documents"]
POLICY_NUMBER_RE = re.compile(r"^[A-Z]{2,5}-\d{4}-\d{3,8}$")
SUMMARY_HEADINGS = ["Claim overview", "Coverage assessment", "Missing information",
                    "Recommended next step"]


@dataclass
class ValidationResult:
    """Outcome of a validation: errors make it invalid, warnings don't."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict | None = None

    def to_dict(self):
        """Serialisable form without the data payload."""
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


class ContentValidator:
    """Checks model output before it is trusted, and filters PII before model calls."""

    # --------------------------------------------------------------- parsing
    @staticmethod
    def parse_json_output(text: str) -> dict:
        """Accepts raw JSON, ```json fenced``` JSON, or JSON embedded in prose."""
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start == -1 or end <= start:
                raise ValueError("No JSON object found in model output")
            return json.loads(cleaned[start:end + 1])

    # ------------------------------------------------------------ extraction
    def validate_extraction(self, text_or_dict, source_text: str | None = None) -> ValidationResult:
        """Check extracted fields for schema, types, formats, plausibility and grounding."""
        errors, warnings = [], []
        if isinstance(text_or_dict, dict):
            data = text_or_dict
        else:
            try:
                data = self.parse_json_output(text_or_dict)
            except (ValueError, json.JSONDecodeError) as e:
                return ValidationResult(False, [f"Invalid JSON: {e}"])
        if not isinstance(data, dict):
            return ValidationResult(False, ["Output is not a JSON object"])

        for f in REQUIRED_FIELDS:
            if f not in data:
                errors.append(f"Missing key: {f}")
            elif data[f] in (None, "", []):
                warnings.append(f"Field '{f}' is empty - not found in document?")

        # claim_amount -> number
        amt = data.get("claim_amount")
        if isinstance(amt, str):
            try:
                data["claim_amount"] = float(re.sub(r"[^\d.\-]", "", amt))
                warnings.append("claim_amount was a string; coerced to number")
            except ValueError:
                errors.append(f"claim_amount not numeric: {amt!r}")
        amt = data.get("claim_amount")
        if isinstance(amt, (int, float)):
            if amt <= 0:
                errors.append("claim_amount must be positive")
            elif amt > 5_000_000:
                warnings.append("claim_amount unusually high - flag for review")

        # incident_date -> ISO, not in future
        d = data.get("incident_date")
        if d:
            try:
                parsed = datetime.strptime(str(d), "%Y-%m-%d").date()
                if parsed > date.today():
                    errors.append("incident_date is in the future")
            except ValueError:
                errors.append(f"incident_date not in YYYY-MM-DD format: {d!r}")

        pn = data.get("policy_number")
        if pn and not POLICY_NUMBER_RE.match(str(pn)):
            warnings.append(f"policy_number '{pn}' does not match expected format XXX-YYYY-NNNN")

        # Grounding: extracted values should literally appear in the source
        if source_text:
            low = source_text.lower()
            for f in ("claimant_name", "policy_number"):
                v = data.get(f)
                if v and str(v).lower() not in low:
                    warnings.append(f"'{f}' value '{v}' not found verbatim in document (possible hallucination)")

        return ValidationResult(not errors, errors, warnings, data)

    # --------------------------------------------------------------- summary
    def validate_summary(self, summary: str, extracted: dict | None = None,
                         min_words: int = 30, max_words: int = 350) -> ValidationResult:
        """Check a summary's structure, citations, factual consistency and PII."""
        errors, warnings = [], []
        words = len(summary.split())
        if words < min_words:
            errors.append(f"Summary too short ({words} words)")
        if words > max_words:
            warnings.append(f"Summary long ({words} words)")
        for h in SUMMARY_HEADINGS:
            if h.lower() not in summary.lower():
                warnings.append(f"Missing section: {h}")
        if not re.search(r"\[Section [\d.]+\]", summary):
            warnings.append("No policy section citations - coverage claim may be ungrounded")
        if extracted:
            pn = extracted.get("policy_number")
            if pn and pn not in summary:
                warnings.append("Policy number not mentioned in summary")
            amt = extracted.get("claim_amount")
            if isinstance(amt, (int, float)):
                nums = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", summary)}
                if amt not in nums:
                    warnings.append(f"Claim amount {amt} not stated in summary")
        if PII_PATTERNS["ssn"].search(summary) or PII_PATTERNS["card"].search(summary):
            errors.append("Summary contains unredacted sensitive data")
        return ValidationResult(not errors, errors, warnings)

    # ----------------------------------------------------- content filtering
    @staticmethod
    def redact_pii(text: str) -> tuple[str, dict[str, int]]:
        """Mask sensitive identifiers before text is sent to a model."""
        counts = {}
        for name, pattern in PII_PATTERNS.items():
            text, n = pattern.subn(f"[REDACTED_{name.upper()}]", text)
            if n:
                counts[name] = n
        return text, counts


# Order matters: the most specific patterns run first.
PII_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "phone": re.compile(r"(?<![\w-])\+?\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4}\b"),
}
