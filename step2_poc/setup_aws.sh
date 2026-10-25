#!/usr/bin/env bash
# Step 2.1 - Set up the AWS environment
# Usage:  bash step2_poc/setup_aws.sh <your-initials> [region]
set -euo pipefail

INITIALS="${1:?Usage: bash step2_poc/setup_aws.sh <your-initials> [region]}"
REGION="${2:-${AWS_REGION:-us-east-1}}"
BUCKET="claim-documents-poc-$(echo "$INITIALS" | tr '[:upper:]' '[:lower:]')"

echo "==> 1. Checking AWS credentials (profile: ${AWS_PROFILE:-default})"
if [ -n "${AWS_PROFILE:-}" ] && [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
  echo "    WARNING: AWS_ACCESS_KEY_ID is set in this shell and overrides AWS_PROFILE."
  echo "    Run: unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN   and try again."
  exit 1
fi
aws sts get-caller-identity --output table
read -r -p "Is this the account you want to use for the assignment? [y/N] " ok
[ "$ok" = "y" ] || { echo "Aborted. Select the right account with: export AWS_PROFILE=<name>"; exit 1; }

echo "==> 2. Creating bucket s3://$BUCKET in $REGION"
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "    bucket already exists - skipping"
else
  aws s3 mb "s3://$BUCKET" --region "$REGION"
fi

echo "==> 3. Blocking public access + default encryption (claims contain PII)"
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

echo "==> 4. Writing .env"
cat > .env <<ENV
AWS_REGION=$REGION
CLAIMS_BUCKET=$BUCKET
MOCK_MODE=0
${AWS_PROFILE:+AWS_PROFILE=$AWS_PROFILE}
ENV
cat .env

echo "==> 5. Bedrock models you can call in $REGION (look for Nova + Titan Embeddings):"
aws bedrock list-inference-profiles --region "$REGION" \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'nova') || contains(inferenceProfileId,'claude')].inferenceProfileId" \
  --output text | tr '\t' '\n' | sort | head -20 || true

cat <<MSG

Done. If a model call later fails with AccessDeniedException, open
Bedrock console -> Model access (or Model catalog) in $REGION and enable:
  - Amazon Nova Micro / Lite / Pro
  - Amazon Titan Text Embeddings V2
  - Anthropic Claude 3 Haiku (optional, for the comparison)
MSG
