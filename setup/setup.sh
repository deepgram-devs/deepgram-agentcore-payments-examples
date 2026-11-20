#!/usr/bin/env bash
# One-time buyer setup for paying AWS Marketplace x402 APIs with AgentCore payments (AWS Billing).
#
#   ./setup/setup.sh [PAYMENT_MANAGER_NAME] [REGION]
#
# Creates, in the account of your current AWS credentials (an administrator identity):
#   1. the AWS Marketplace service-linked role AWSServiceRoleForMarketplaceAgenticCommerce (once per account)
#   2. the Payment Manager service role (trusted by bedrock-agentcore.amazonaws.com)
#   3. a Payment Manager (IAM authorization)
#   4. an AWS Billing payment connector on it
# and prints `export PAYMENT_MANAGER_ARN=...`.
#
# Needs AWS CLI v2.41.2+ (earlier versions lack the AwsBilling connector type).
# Docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-manager.html
set -euo pipefail

NAME="${1:-DeepgramPayments}"
REGION="${2:-${AWS_REGION:-us-east-1}}"
ROLE_NAME="AgentCorePaymentsResourceRetrievalRole"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

echo "Account $ACCOUNT, region $REGION, payment manager $NAME" >&2

# 1. Service-linked role (AWS Marketplace creates/accepts the purchase agreement and meters usage through it).
if ! aws iam get-role --role-name AWSServiceRoleForMarketplaceAgenticCommerce >/dev/null 2>&1; then
  aws iam create-service-linked-role --aws-service-name agentcore-payments.marketplace.amazonaws.com >/dev/null
  echo "created AWSServiceRoleForMarketplaceAgenticCommerce" >&2
fi

# 2. Payment Manager service role. AgentCore payments attaches its permissions when the manager is created.
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Principal\": {\"Service\": \"bedrock-agentcore.amazonaws.com\"},
      \"Action\": \"sts:AssumeRole\",
      \"Condition\": {
        \"StringEquals\": {\"aws:SourceAccount\": \"$ACCOUNT\"},
        \"ArnLike\": {\"aws:SourceArn\": \"arn:aws:bedrock-agentcore:$REGION:$ACCOUNT:payment-manager/*\"}
      }
    }]
  }" >/dev/null
  echo "created $ROLE_NAME" >&2
  sleep 10 # IAM propagation
fi

# 3. Payment Manager.
MANAGER_ID=$(aws bedrock-agentcore-control create-payment-manager --region "$REGION" \
  --name "$NAME" --authorizer-type AWS_IAM \
  --role-arn "arn:aws:iam::$ACCOUNT:role/$ROLE_NAME" \
  --query paymentManagerId --output text)
until [ "$(aws bedrock-agentcore-control get-payment-manager --region "$REGION" \
  --payment-manager-id "$MANAGER_ID" --query status --output text)" = READY ]; do sleep 5; done
MANAGER_ARN=$(aws bedrock-agentcore-control get-payment-manager --region "$REGION" \
  --payment-manager-id "$MANAGER_ID" --query paymentManagerArn --output text)

# 4. AWS Billing connector (no credential provider: the service binds the service-linked role).
aws bedrock-agentcore-control create-payment-connector --region "$REGION" \
  --payment-manager-id "$MANAGER_ID" --name AwsBillingConnector --type AwsBilling >/dev/null

echo "export PAYMENT_MANAGER_ARN=$MANAGER_ARN"
