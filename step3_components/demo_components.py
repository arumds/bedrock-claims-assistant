"""Step 3 - See each reusable component on its own.

  python step3_components/demo_components.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from step3_components.content_validator import ContentValidator  # noqa: E402
from step3_components.model_invoker import ModelInvoker  # noqa: E402
from step3_components.prompt_manager import PromptTemplateManager  # noqa: E402

print("1) PromptTemplateManager")
pm = PromptTemplateManager()
print("   templates:", pm.list())
system, user, t = pm.render("extract_info", document_text="Claimant Name: Test Person ...")
print(f"   extract_info v{t.version}, temperature={t.temperature}, vars={t.variables}")
try:
    pm.render("generate_summary", extracted_info="{}")
except ValueError as e:
    print("   missing-variable guard ->", e)

print("\n2) ContentValidator")
v = ContentValidator()
good = '```json\n{"claimant_name": "Test Person", "policy_number": "AUTO-2025-000001", ' \
       '"incident_date": "2026-01-05", "claim_amount": "1,200.50", "incident_description": "Dent"}\n```'
r = v.validate_extraction(good)
print("   fenced JSON + string amount ->", r.to_dict(), "| amount:", r.data["claim_amount"])
bad = '{"claimant_name": null, "incident_date": "05/01/2026", "claim_amount": -5}'
print("   bad output ->", v.validate_extraction(bad).to_dict())
masked, counts = v.redact_pii("SSN 123-45-6789, mail a@b.com, IBAN FI21 1234 5600 0007 85")
print("   redact_pii ->", masked, counts)

print("\n3) ModelInvoker", "(MOCK)" if config.MOCK_MODE else f"({config.REGION})")
inv = ModelInvoker()
resp = inv.invoke(config.SUMMARY_MODEL, "In one sentence, what is subrogation in insurance?",
                  system="Be concise.", max_tokens=100)
print(f"   {resp.model_id}: {resp.latency_s:.2f}s, {resp.input_tokens}+{resp.output_tokens} tokens,"
      f" est ${resp.est_cost_usd or 0:.6f}")
print("  ", resp.text)
