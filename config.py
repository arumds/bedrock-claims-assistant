"""Central configuration. Every value can be overridden with an environment
variable or a `.env` file in the project root (see `.env.example`)."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Tiny .env loader so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def _inference_profile_prefix(region: str) -> str:
    """Cross-region inference profile prefix for the region (us./eu./apac.)."""
    if region.startswith("us-"):
        return "us."
    if region.startswith("eu-"):
        return "eu."
    if region.startswith("ap-"):
        return "apac."
    return ""


PREFIX = os.getenv("BEDROCK_PROFILE_PREFIX", _inference_profile_prefix(REGION))

# --- AWS credentials ----------------------------------------------------------
# If AWS_PROFILE is set (setup_aws.sh writes it to .env), use that profile
# *explicitly*. An explicit profile makes boto3 ignore stray AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY variables in the shell, which otherwise take precedence
# and cause InvalidAccessKeyId / InvalidClientTokenId errors.
AWS_PROFILE = os.getenv("AWS_PROFILE")


def _use_profile_explicitly() -> None:
    """Make every boto3.client() in this project use AWS_PROFILE, even if loose keys are exported."""
    if not AWS_PROFILE or os.getenv("MOCK_MODE", "0").lower() in ("1", "true", "yes"):
        return
    try:
        import boto3
        from botocore.exceptions import ProfileNotFound
    except ImportError:
        return
    if os.getenv("AWS_ACCESS_KEY_ID"):
        print(f"[config] Ignoring AWS_ACCESS_KEY_ID from your shell - using profile '{AWS_PROFILE}' from .env")
    try:
        boto3.setup_default_session(profile_name=AWS_PROFILE, region_name=REGION)
    except ProfileNotFound:
        raise SystemExit(f"AWS profile '{AWS_PROFILE}' not found. Create it with: "
                         f"aws configure --profile {AWS_PROFILE}")


_use_profile_explicitly()

# --- Bucket -----------------------------------------------------------------
BUCKET = os.getenv("CLAIMS_BUCKET", "claim-documents-poc-xyz")
CLAIMS_PREFIX = "claims/"
POLICIES_PREFIX = "policies/"
RESULTS_PREFIX = "results/"
FEEDBACK_PREFIX = "feedback/"

# --- Model selection (Step 1) -----------------------------------------------
# Document understanding + information extraction: needs strong reasoning,
# multimodal input (PDF / scanned images) and reliable JSON -> Nova Pro.
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", f"{PREFIX}amazon.nova-pro-v1:0")
# Summary generation: short, well-grounded prose -> fast & cheap Nova Lite.
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", f"{PREFIX}amazon.nova-lite-v1:0")
# Embeddings for the RAG policy knowledge base.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")

# Judge model for LLM-as-a-judge summary scoring in Step 4. Ideally a model
# that is NOT one of the models being compared, to limit self-preference bias.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", f"{PREFIX}amazon.nova-pro-v1:0")

# Models compared in Step 4 (comma separated override).
COMPARE_MODELS = [
    m.strip()
    for m in os.getenv(
        "COMPARE_MODELS",
        ",".join(
            [
                f"{PREFIX}amazon.nova-micro-v1:0",
                f"{PREFIX}amazon.nova-lite-v1:0",
                f"{PREFIX}amazon.nova-pro-v1:0",
                f"{PREFIX}anthropic.claude-3-haiku-20240307-v1:0",
            ]
        ),
    ).split(",")
    if m.strip()
]

# --- Behaviour --------------------------------------------------------------
# MOCK_MODE=1 runs everything offline: a deterministic fake model and a local
# folder instead of S3. Great for testing the pipeline at zero AWS cost.
MOCK_MODE = os.getenv("MOCK_MODE", "0").lower() in ("1", "true", "yes")
LOCAL_STORE_DIR = PROJECT_ROOT / ".local_s3"
RESULTS_DIR = PROJECT_ROOT / "step4_test_evaluate" / "results"
SAMPLE_DIR = PROJECT_ROOT / "sample_data"

# Rough on-demand prices (USD per 1K tokens, input/output) used only to
# estimate cost in the comparison report. Check the Bedrock pricing page for
# your region; unknown models are reported without a cost.
PRICING_PER_1K = {
    "amazon.nova-micro-v1:0": (0.000035, 0.00014),
    "amazon.nova-lite-v1:0": (0.00006, 0.00024),
    "amazon.nova-pro-v1:0": (0.0008, 0.0032),
    "anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
    "anthropic.claude-3-5-haiku-20241022-v1:0": (0.0008, 0.004),
}


def price_for(model_id: str):
    """Return (input, output) USD per 1K tokens for a model ID, ignoring the region prefix."""
    base = model_id.split(".", 1)[1] if model_id.split(".", 1)[0] in ("us", "eu", "apac", "global") else model_id
    return PRICING_PER_1K.get(base)
