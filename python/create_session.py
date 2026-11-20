"""Create a payment session with a spend limit, and print `export PAYMENT_SESSION_ID=...`.

    uv run create_session.py [MAX_SPEND_USD] [EXPIRY_MINUTES]

Run this with the session-manager identity, not the agent's identity: AWS recommends
that no single role can both create sessions (set budgets) and call ProcessPayment.
"""

import os
import sys

import boto3

max_usd = sys.argv[1] if len(sys.argv) > 1 else "1.00"
minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 60  # 15-480
arn = os.environ["PAYMENT_MANAGER_ARN"]
client = boto3.client("bedrock-agentcore", region_name=arn.split(":")[3])
session = client.create_payment_session(
    paymentManagerArn=arn,
    userId=os.environ.get("PAYMENT_USER_ID", "deepgram-example-user"),  # required; ProcessPayment must use the same one
    expiryTimeInMinutes=minutes,
    limits={"maxSpendAmount": {"value": max_usd, "currency": "USD"}},
)["paymentSession"]
print(f"export PAYMENT_SESSION_ID={session['paymentSessionId']}")
print(f"# spend limit ${max_usd}, expires in {minutes} min", file=sys.stderr)
