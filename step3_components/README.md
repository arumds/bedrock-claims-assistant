# Step 3 – Create reusable components (Skill 1.1.3)

Three standardised components, plus the Step 2 processor rebuilt on top of them.

```bash
python step3_components/demo_components.py          # see each component on its own
python step3_components/claim_pipeline.py --all     # full pipeline using all three
```

## 3.1 Prompt template manager – `prompt_manager.py`

- `PromptTemplate` is a dataclass with a **name, version, system prompt, user prompt, temperature and max_tokens**. Each prompt carries its recommended inference settings.
- `render(name, **vars)` returns `(system, user, template)` and **raises an error if a placeholder is missing** instead of silently sending `{policy_context}` to the model.
- The templates are `extract_info` (v1.1), `repair_json` (v1.0), `generate_summary` (v1.2) and `judge_summary` (v1.0, used in Step 4). Template versions are saved with each result, so a change in quality can be traced back to a prompt change.
- `get_prompt()` is kept, so the course snippet still works.

## 3.2 Model invoker – `model_invoker.py`

- One `invoke()` for **any Bedrock chat model** via the Converse API, with optional system prompt and document attachment.
- `invoke_template()` renders a template and invokes the model with that template's settings.
- **Retries with exponential backoff and jitter** on `ThrottlingException`, `ServiceUnavailable` and similar errors.
- Returns a `ModelResponse` with **latency, input/output tokens, stop reason and estimated cost**. Step 4 uses these.
- `embed()` for Titan embeddings.
- `mock=True` gives offline, zero-cost runs.

## 3.3 Basic content validator – `content_validator.py`

| Check | Examples |
|---|---|
| JSON parsing | accepts ```` ```json ```` fences or JSON surrounded by text |
| Schema | required keys present; empty fields become warnings |
| Types and format | `claim_amount` numeric and > 0 (`"€1,000"` is coerced to `1000.0`); `incident_date` in YYYY-MM-DD and not in the future; policy-number pattern |
| Grounding | `claimant_name` and `policy_number` must appear in the source document (catches hallucinations) |
| Summary | required sections present, `[Section x.y]` citations, claim amount and policy number stated, no PII leaked |
| **Content filter** | `redact_pii()` masks SSNs, IBANs, card numbers, e-mails and phone numbers **before** text reaches a model |

## 3.4 The components together – `claim_pipeline.py`

```
document → redact_pii → extract_info ──► validate ──invalid──► repair_json ──► validate
                                            │ valid
                                            ▼
                           RAG retrieve → generate_summary → validate_summary → results/*.v2.json
```

Compare with Step 2 by running claim 002 again:

```bash
python step3_components/claim_pipeline.py claims/claim_002_home_water_damage.txt
```

You'll see `PII redacted: {'ssn': 1, 'iban': 1}`, the validation results for the extraction and the summary, and the total latency, tokens and cost.

Unit tests (offline): `python -m pytest -q`

➡ Next: [Step 4 – Test and evaluate](../step4_test_evaluate/README.md)
