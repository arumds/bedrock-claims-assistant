# Extras – the "extra challenging steps"

| Extension | Where | Status |
|---|---|---|
| Simple web interface using Flask | `extras/web_app.py` | ✅ |
| Knowledge base with policy information | `step2_poc/policy_rag.py` (Titan embeddings + vector index) | ✅ PoC version; Bedrock Knowledge Bases upgrade described below |
| Content filtering for sensitive information | `ContentValidator.redact_pii` in `step3_components/content_validator.py` | ✅ |
| Simple feedback mechanism | 👍/👎 + comment in the web UI → `s3://…/feedback/` and `extras/feedback.jsonl` | ✅ |
| Cleanup | `extras/cleanup.sh` | ✅ |

## Web interface

```bash
python extras/web_app.py
# open http://127.0.0.1:5000
```

Upload a claim, or pick one already in the bucket. The page shows the PII that was redacted, the extracted fields with validation warnings, the policy sections used, the summary and the metrics. Rate each result with 👍/👎; feedback is saved with the model IDs and prompt versions, so ratings can be traced to a configuration.

## Upgrading to Amazon Bedrock Knowledge Bases (optional)

1. Bedrock console → **Knowledge Bases → Create** → data source: `s3://claim-documents-poc-xx/policies/`
2. Embeddings: Titan Text Embeddings V2. Vector store: *Quick create* (S3 Vectors or OpenSearch Serverless).
3. **Sync**, then replace `kb.retrieve(...)` with:

```python
agent_rt = boto3.client("bedrock-agent-runtime")
resp = agent_rt.retrieve(knowledgeBaseId="KBID",
                         retrievalQuery={"text": query},
                         retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 4}})
hits = [{"text": r["content"]["text"], "score": r["score"]} for r in resp["retrievalResults"]]
```

⚠ An OpenSearch Serverless collection is billed hourly even when idle. Delete it when you're done.

## Cleanup

```bash
bash extras/cleanup.sh     # deletes the bucket + local caches (asks first)
```
