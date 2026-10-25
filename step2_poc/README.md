# Step 2 – Implement the proof of concept (Skill 1.1.2)

Run every command from the **project root** (`..`), with your virtualenv active.

## 2.1 Set up the AWS environment

```bash
bash step2_poc/setup_aws.sh <your-initials> eu-central-1
```

The script:
1. checks your credentials
2. creates `s3://claim-documents-poc-<initials>` (the assignment's `aws s3 mb` command)
3. blocks public access and turns on default encryption
4. writes `.env` with the region and bucket name
5. lists the Nova and Claude inference profiles available in your region

If you'd rather do it by hand: `aws s3 mb s3://claim-documents-poc-<initials>`, then copy `.env.example` to `.env` and edit it.

## 2.2 Document upload functionality

```bash
python step2_poc/upload_documents.py              # uploads sample_data/claims/* and sample_data/policies/*
python step2_poc/upload_documents.py --list       # shows what's in the bucket
python step2_poc/upload_documents.py my_claim.pdf # upload your own claim (txt, md, pdf, docx …)
```

Code: `s3_storage.py` (S3 wrapper, uploads with SSE) and `upload_documents.py` (CLI with a file-type allow-list).

## 2.3 Simple RAG component using policy information

```bash
python step2_poc/policy_rag.py "pipe leaking for weeks under the sink" --policy HOME-2024-118902
```

Example output (live Titan embeddings; scores vary):
```
0.61  [Section 2.2] Gradual leakage and seepage exclusion  (home_policy_HOME.md)
0.55  [Section 2.1] Sudden and accidental water damage     (home_policy_HOME.md)
...
```

How it works (`policy_rag.py`):
1. reads the policies from `s3://…/policies/`
2. splits them into chunks, one per `## [Section x.y]`
3. embeds each chunk with **Titan Text Embeddings V2** and caches the vectors in `.rag_index.json`
4. at query time, keeps only chunks for the claim's product (`HOME-…` → HOME policy), embeds the query and ranks by cosine similarity

## 2.4 Bedrock integration + claim summary generation

```bash
python step2_poc/claim_processor.py claims/claim_001_auto_collision.txt
python step2_poc/claim_processor.py --all
```

`claim_processor.py` deliberately keeps prompts inline and calls `boto3` directly, so every request sent to Bedrock is visible:

| Stage | Code | Model call |
|---|---|---|
| Read from S3 | `load_document()` | – (PDF/DOCX are passed to the model as a Converse `document` block) |
| Extract fields | `EXTRACT_PROMPT` | `converse(EXTRACTION_MODEL, temperature=0)` |
| Retrieve policy clauses | `kb.retrieve(...)` | Titan embeddings |
| Generate summary | `SUMMARY_PROMPT` | `converse(SUMMARY_MODEL, temperature=0.3)` |
| Save response | `store.put_json("results/…")` | – |

**Try this:** run claim 002 and look at what was sent to the model. The SSN and IBAN go through unredacted, and nothing checks the JSON. Step 3 fixes both.

➡ Next: [Step 3 – Create reusable components](../step3_components/README.md)
