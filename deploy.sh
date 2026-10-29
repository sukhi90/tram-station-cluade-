#!/bin/bash
# One command delivery: tests -> S3 upload -> CloudFormation -> (reboot if the stack already existed)
# Usage: bash deploy.sh [stack-name]
set -euo pipefail
STACK=${1:-tram}
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="tram-artifacts-${ACCOUNT}-${REGION}"

echo "== 1. tests (a failing test blocks the delivery)"
if ! python3 -m unittest discover -s tests; then
  echo
  echo "TESTS FAILED - DELIVERY BLOCKED. Nothing was uploaded or changed in AWS."
  exit 1
fi

echo "== 2. artifact bucket: $BUCKET"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  || echo "(could not set public access block - continuing)"
aws s3 sync app/ "s3://$BUCKET/app" --delete --exclude "__pycache__/*"

echo "== 3. network (default VPC)"
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text)
SUBNET=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
  --query "Subnets[0].SubnetId" --output text)
echo "$VPC $SUBNET"

EXISTED=0
aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1 && EXISTED=1

echo "== 4. CloudFormation deploy"
aws cloudformation deploy --template-file template.yaml --stack-name "$STACK" \
  --parameter-overrides VpcId="$VPC" SubnetId="$SUBNET" ArtifactBucket="$BUCKET" \
  --capabilities CAPABILITY_IAM

OUT() { aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

if [ "$EXISTED" -eq 1 ]; then
  echo "== 5. stack existed: reboot instance so it loads the new app files"
  aws ec2 reboot-instances --instance-ids "$(OUT InstanceId)"
fi
echo
echo "DELIVERED. PUBLIC URL: $(OUT PublicUrl)   (allow 1-2 minutes after a first deploy or reboot)"
