# Bonus Assignment – Insurance Claim Document Processing with Amazon Bedrock

AWS Certified Generative AI Developer exam prep, **Task 1.1: Analyze requirements and design GenAI solutions.**

A proof of concept that stores claim documents in Amazon S3, extracts structured data with an Amazon Bedrock foundation model, checks the claim against the policy wording with a simple RAG component, and generates a grounded claim summary.

The folders follow the assignment steps. Work through them in order:

| Step | Folder | What you do | Skill |
|---|---|---|---|
| 0 | *(this page)* | Install and choose live or offline mode | – |
| 1 | [`step1_architecture/`](step1_architecture/README.md) | Read the architecture and the model choices | 1.1.1 |
| 2 | [`step2_poc/`](step2_poc/README.md) | Create the bucket, upload documents, build the RAG index, process claims | 1.1.2 |
| 3 | [`step3_components/`](step3_components/README.md) | Reusable prompt manager, model invoker and validator, plus the refactored pipeline | 1.1.3 |
| 4 | [`step4_test_evaluate/`](step4_test_evaluate/README.md) | Test 3 sample documents, compare 4 models, evaluate on the 4 criteria (extraction accuracy, summary quality, time and efficiency, code organisation), write up findings | – |
| + | [`extras/`](extras/README.md) | Flask web UI, feedback, PII filter, cleanup | stretch goals |

```
Assignment1/
├── README.md                ← you are here
├── config.py                ← region, bucket, model IDs (env-overridable)
├── mock_bedrock.py          ← offline fake model for MOCK_MODE=1
├── requirements.txt  .env.example  .gitignore
├── sample_data/
│   ├── claims/              ← 3 sample claims: auto, home (contains PII), health
│   ├── policies/            ← policy wording used by the RAG step
│   └── ground_truth.json    ← expected answers used to score models in Step 4
├── step1_architecture/      ← architecture.png / .svg + model selection
├── step2_poc/               ← setup_aws.sh, s3_storage, upload_documents, policy_rag, claim_processor
├── step3_components/        ← prompt_manager, model_invoker, content_validator, claim_pipeline
├── step4_test_evaluate/     ← compare_models.py (4-criteria evaluation), code_quality.py, FINDINGS.md
├── extras/                  ← web_app.py, cleanup.sh
└── tests/                   ← offline unit tests
```

---

## Step 0 – Install

Open a terminal in this folder (`bedrock-claims-assistant`):

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Option A: run offline first (recommended, free)

Every script works without AWS when you set `MOCK_MODE=1`. A regex-based fake model replaces Bedrock and a local `.local_s3/` folder replaces S3, so you can check the whole flow before spending anything:

```bash
export MOCK_MODE=1
python step2_poc/upload_documents.py
python step2_poc/claim_processor.py --all
python -m pytest -q                 # 8 tests should pass
```

### Option B: run against AWS

You need:
- AWS CLI v2 configured (`aws configure` or `aws sso login`) with S3 and Bedrock permissions.
- Bedrock model access enabled in your region for **Amazon Nova Micro, Lite and Pro**, **Titan Text Embeddings V2** and, optionally, **Claude 3 Haiku**. Some regions now enable these by default; otherwise enable them under *Bedrock console → Model access*.

Then go to Step 1 and follow the steps in order. `bash step2_poc/setup_aws.sh <initials> <region>` creates the bucket and writes `.env` for you.

> **Region tip:** you are in Finland, so `eu-central-1` (Frankfurt) or `eu-north-1` (Stockholm) are good choices. The code picks the `eu.` cross-region inference profiles automatically from `AWS_REGION`.

## Cost and cleanup

A full run of all four steps sends about 50 small model calls (including the judge). With Nova models that costs well under USD 0.20. S3 storage is a few KB. When you're finished:

```bash
bash extras/cleanup.sh
```

This project is for learning. You are responsible for any AWS charges, so set a billing alert.

## Sharing

Tag **#awsexamprep** when you post. Good things to show: `step1_architecture/architecture.png`, the scorecard from `step4_test_evaluate/results/evaluation_report.md`, and your `FINDINGS.md`.
