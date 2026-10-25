"""Offline unit tests:  MOCK_MODE=1 python -m pytest -q"""
import os
import sys
from pathlib import Path

os.environ["MOCK_MODE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from step3_components.content_validator import ContentValidator  # noqa: E402
from step3_components.prompt_manager import PromptTemplateManager  # noqa: E402

v = ContentValidator()


def test_prompt_render_and_missing_vars():
    """Templates render, and missing variables or names raise errors."""
    pm = PromptTemplateManager()
    system, user, t = pm.render("extract_info", document_text="hello")
    assert "hello" in user and t.temperature == 0.0
    with pytest.raises(ValueError):
        pm.render("generate_summary", extracted_info="{}")
    with pytest.raises(ValueError):
        pm.get("nope")


def test_parse_fenced_json():
    """JSON inside ``` fences and prose is parsed."""
    assert v.parse_json_output('Here you go:\n```json\n{"a": 1}\n```')["a"] == 1


def test_valid_extraction_coerces_amount():
    """A currency string amount is coerced to a number."""
    r = v.validate_extraction('{"claimant_name":"A B","policy_number":"AUTO-2025-000001",'
                              '"incident_date":"2026-01-01","claim_amount":"€1,000.00",'
                              '"incident_description":"x"}')
    assert r.valid and r.data["claim_amount"] == 1000.0


def test_invalid_extraction():
    """Future dates and negative amounts are rejected."""
    r = v.validate_extraction('{"claimant_name":"A","policy_number":"X","incident_date":"2999-01-01",'
                              '"claim_amount":-1,"incident_description":"x"}')
    assert not r.valid
    assert any("future" in e for e in r.errors) and any("positive" in e for e in r.errors)


def test_hallucination_warning():
    """Values not in the source document raise a warning."""
    r = v.validate_extraction({"claimant_name": "Ghost", "policy_number": "AUTO-2025-000001",
                               "incident_date": "2026-01-01", "claim_amount": 5,
                               "incident_description": "x"}, source_text="Policy AUTO-2025-000001")
    assert any("Ghost" in w for w in r.warnings)


def test_redaction():
    """SSN, IBAN and e-mail are masked."""
    text, counts = v.redact_pii("ID 123-45-6789 IBAN FI21 1234 5600 0007 85 mail x@y.com")
    assert "6789" not in text and "5600" not in text and "x@y.com" not in text
    assert counts == {"ssn": 1, "iban": 1, "email": 1}


def test_pipeline_end_to_end_mock():
    """The full pipeline runs offline and redacts PII."""
    from step2_poc.upload_documents import main as upload_main
    from step3_components.claim_pipeline import ClaimPipeline
    sys.argv = ["upload"]
    upload_main()
    r = ClaimPipeline().process("claims/claim_002_home_water_damage.txt", save=False)
    assert r["extracted_info"]["policy_number"] == "HOME-2024-118902"
    assert r["pii_redacted"].get("ssn") == 1
    assert any("Section 2." in s for s in r["policy_sections_used"])


def test_evaluation_scoring():
    """Step 4 scoring: field matching, verdict parsing, key-fact recall, retrieval recall."""
    from step4_test_evaluate.compare_models import (field_correct, key_fact_recall,
                                                    retrieval_recall, verdict_of)
    assert field_correct("claim_amount", "3060", 3060.0)
    assert field_correct("claimant_name", "maria virtanen ", "Maria Virtanen")
    assert not field_correct("incident_date", None, "2026-03-03")
    assert verdict_of("**Coverage assessment:** Likely not covered - see [Section 2.2]") == "likely not covered"
    assert verdict_of("**Coverage assessment:** Likely covered") == "likely covered"
    facts = [{"fact": "A", "any_of": ["gradual"]}, {"fact": "B", "any_of": ["2,500"]}]
    assert key_fact_recall("Gradual leak excluded", facts) == (0.5, ["B"])
    r = {"policy_sections_used": ["[Section 2.1] x", "[Section 2.2] y"]}
    assert retrieval_recall(r, ["2.1", "2.2", "2.3", "2.5"]) == 0.5
