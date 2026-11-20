"""One-time buyer setup for paying AWS Marketplace x402 APIs with AgentCore payments (AWS Billing).

    uv run setup_account.py [PAYMENT_MANAGER_NAME] [REGION]

Run as an administrator. Safe to re-run: it reuses whatever already exists. Creates:
  1. the AWS Marketplace service-linked role AWSServiceRoleForMarketplaceAgenticCommerce (once per account)
  2. the Payment Manager service role, trusted by bedrock-agentcore.amazonaws.com, with its base permissions
  3. a Payment Manager (IAM authorization)
  4. an AWS Billing payment connector on it
and prints `export PAYMENT_MANAGER_ARN=...`.

Docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-manager.html
"""

import json
import sys
import time

import boto3

NAME = sys.argv[1] if len(sys.argv) > 1 else "DeepgramPayments"
REGION = sys.argv[2] if len(sys.argv) > 2 else "us-east-1"
ROLE_NAME = "AgentCorePaymentsResourceRetrievalRole"
SLR_NAME = "AWSServiceRoleForMarketplaceAgenticCommerce"

iam = boto3.client("iam")
control = boto3.client("bedrock-agentcore-control", region_name=REGION)
account = boto3.client("sts").get_caller_identity()["Account"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def role_exists(name: str) -> bool:
    try:
        iam.get_role(RoleName=name)
        return True
    except iam.exceptions.NoSuchEntityException:
        return False


log(f"Account {account}, region {REGION}, payment manager {NAME}")

# 1. Service-linked role: AWS Marketplace uses it to create/accept the purchase agreement and meter usage.
if not role_exists(SLR_NAME):
    iam.create_service_linked_role(AWSServiceName="agentcore-payments.marketplace.amazonaws.com")
    log(f"created {SLR_NAME}")

# 2. Payment Manager service role. A role you create yourself (unlike one the console creates) needs the
#    base permissions below, or CreatePaymentManager fails with "Access denied while creating workload identity".
if not role_exists(ROLE_NAME):
    iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{account}:payment-manager/*"},
                },
            }],
        }),
    )
    log(f"created {ROLE_NAME}")
wid = f"arn:aws:bedrock-agentcore:{REGION}:{account}:workload-identity-directory/default"
iam.put_role_policy(
    RoleName=ROLE_NAME,
    PolicyName="AgentCorePaymentsBase",
    PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "WorkloadIdentityManagement", "Effect": "Allow",
             "Action": ["bedrock-agentcore:CreateWorkloadIdentity", "bedrock-agentcore:DeleteWorkloadIdentity"],
             "Resource": [wid, f"{wid}/workload-identity/*"]},
            {"Sid": "WorkloadIdentityAccess", "Effect": "Allow",
             "Action": "bedrock-agentcore:GetWorkloadAccessToken",
             "Resource": [wid, f"{wid}/workload-identity/*"]},
            {"Sid": "PaymentTokenBaseAccess", "Effect": "Allow",
             "Action": "bedrock-agentcore:GetResourcePaymentToken",
             "Resource": [f"arn:aws:bedrock-agentcore:{REGION}:{account}:token-vault/default", wid,
                          f"{wid}/workload-identity/*"]},
        ],
    }),
)

# 3. Payment Manager (reuse one with this name if it exists).
managers = control.list_payment_managers().get("paymentManagers", [])
manager = next((m for m in managers if m["name"] == NAME), None)
if manager is None:
    time.sleep(10)  # let the new role/policy propagate
    manager = control.create_payment_manager(
        name=NAME, authorizerType="AWS_IAM", roleArn=f"arn:aws:iam::{account}:role/{ROLE_NAME}"
    )
    log(f"created payment manager {manager['paymentManagerId']}")
manager_id = manager["paymentManagerId"]
while (manager := control.get_payment_manager(paymentManagerId=manager_id))["status"] != "READY":
    if manager["status"].endswith("FAILED"):
        sys.exit(f"payment manager {manager_id} is {manager['status']}")
    time.sleep(5)

# 4. AWS Billing connector (no credential provider: the service binds the service-linked role).
connectors = control.list_payment_connectors(paymentManagerId=manager_id).get("paymentConnectors", [])
if not any(c.get("type") == "AwsBilling" for c in connectors):
    connector = control.create_payment_connector(paymentManagerId=manager_id, name="AwsBillingConnector", type="AwsBilling")
    log(f"created AWS Billing connector {connector['paymentConnectorId']}")

print(f"export PAYMENT_MANAGER_ARN={manager['paymentManagerArn']}")
