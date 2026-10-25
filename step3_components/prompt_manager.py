"""Reusable component #1 - Prompt template manager.

Templates are versioned, carry their own system prompt and recommended
inference settings, and validate that every placeholder is supplied.
"""
from __future__ import annotations

import string
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptTemplate:
    """A versioned prompt: system and user text plus recommended inference settings."""
    name: str
    version: str
    system: str
    user: str
    temperature: float = 0.0
    max_tokens: int = 1000
    description: str = ""

    @property
    def variables(self) -> set[str]:
        """Placeholder names used in the user prompt."""
        return {f for _, f, _, _ in string.Formatter().parse(self.user) if f}


DEFAULT_TEMPLATES = [
    PromptTemplate(
        name="extract_info",
        version="1.1",
        description="Structured field extraction from a claim document",
        system=(
            "You are an insurance claims intake specialist. You extract facts "
            "exactly as written in the document. Never invent values: if a "
            "field is not present, use null. Respond with a single JSON object "
            "and nothing else."
        ),
        user="""Extract the following fields from the insurance claim document below.

Return JSON with exactly these keys:
{{
  "claimant_name": string | null,
  "policy_number": string | null,
  "claim_type": "auto" | "home" | "health" | "other",
  "incident_date": "YYYY-MM-DD" | null,
  "claim_amount": number | null,          // numeric value only, no currency symbol
  "currency": string | null,              // e.g. "USD", "EUR"
  "incident_location": string | null,
  "incident_description": string | null,  // 1-3 sentences
  "supporting_documents": [string]        // documents mentioned as attached
}}

<document>
{document_text}
</document>""",
        temperature=0.0,
        max_tokens=1000,
    ),
    PromptTemplate(
        name="repair_json",
        version="1.0",
        description="Ask the model to fix output that failed validation",
        system="You fix malformed JSON. Respond with corrected JSON only.",
        user="""The following output failed validation with these errors:
{errors}

Original output:
{bad_output}

Return a corrected JSON object with the same keys. Use null for unknown values.""",
        temperature=0.0,
        max_tokens=1000,
    ),
    PromptTemplate(
        name="generate_summary",
        version="1.2",
        description="Claim summary grounded in extracted data + policy clauses (RAG)",
        system=(
            "You are a senior claims adjuster writing a briefing for a "
            "colleague. Use ONLY the extracted claim data and the policy "
            "excerpts provided. Cite policy sections like [Section 3.2]. If "
            "the excerpts do not settle coverage, say so instead of guessing."
        ),
        user="""Extracted claim data:
{extracted_info}

Relevant policy excerpts (retrieved from the policy knowledge base):
{policy_context}

Write the claim summary in this format:

**Claim overview:** 2-3 sentences (who, what, when, how much).
**Coverage assessment:** Likely covered / Likely not covered / Needs review - with the reason and section citations.
**Deductible & limits:** what applies, if stated in the excerpts.
**Missing information:** bullet list, or "None".
**Recommended next step:** one sentence.""",
        temperature=0.3,
        max_tokens=600,
    ),
    PromptTemplate(
        name="judge_summary",
        version="1.0",
        description="LLM-as-a-judge rubric for summary quality (Step 4 evaluation)",
        system=(
            "You are a strict quality reviewer for insurance claim summaries. "
            "Score only against the source material provided. Respond with JSON only."
        ),
        user="""Rate the summary below against the source claim document and policy excerpts.

<claim_document>
{document_text}
</claim_document>

<policy_excerpts>
{policy_context}
</policy_excerpts>

<summary>
{summary}
</summary>

Score each criterion from 1 (poor) to 5 (excellent):
- faithfulness: every statement is supported by the document or excerpts; no invented facts
- completeness: covers claimant, incident, amount, coverage decision, deductible/limits, missing info
- coverage_reasoning: the coverage verdict is correct given the policy excerpts and cites the right sections
- clarity: concise, well structured, easy for an adjuster to act on

Return JSON: {{"faithfulness": int, "completeness": int, "coverage_reasoning": int,
"clarity": int, "issues": [short strings]}}""",
        temperature=0.0,
        max_tokens=400,
    ),
]


class PromptTemplateManager:
    """Registry of prompt templates with safe rendering."""
    def __init__(self, templates: list[PromptTemplate] | None = None):
        self._templates: dict[str, PromptTemplate] = {}
        for t in templates or DEFAULT_TEMPLATES:
            self.register(t)

    def register(self, template: PromptTemplate) -> None:
        """Add or replace a template."""
        self._templates[template.name] = template

    def get(self, name: str) -> PromptTemplate:
        """Return a template by name, or raise ValueError listing what exists."""
        try:
            return self._templates[name]
        except KeyError:
            raise ValueError(
                f"Template '{name}' not found. Available: {sorted(self._templates)}"
            ) from None

    def list(self) -> list[str]:
        """Names of all registered templates."""
        return sorted(self._templates)

    def render(self, name: str, **kwargs) -> tuple[str, str, PromptTemplate]:
        """Return (system_prompt, user_prompt, template)."""
        t = self.get(name)
        missing = t.variables - kwargs.keys()
        if missing:
            raise ValueError(f"Template '{name}' missing variables: {sorted(missing)}")
        return t.system, t.user.format(**kwargs), t

    # Backwards compatible with the course snippet
    def get_prompt(self, template_name: str, **kwargs) -> str:
        """Render only the user prompt (kept for compatibility with the course snippet)."""
        return self.render(template_name, **kwargs)[1]
