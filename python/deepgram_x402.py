"""Call Deepgram's AWS Marketplace x402 endpoint, paying with Amazon Bedrock AgentCore payments.

Flow (x402 v2, AWS Billing):
  1. POST the request unpaid -> HTTP 402 with a base64-JSON PAYMENT-REQUIRED header.
  2. Pick the `accepts` entry whose network is "aws:base" and pass it UNCHANGED to
     AgentCore payments ProcessPayment (paymentType AWS_BILLING_X402).
  3. Retry the same request with PAYMENT-SIGNATURE = base64(JSON
     {"x402Version": 2, "resource": ..., "accepted": <entry>, "payload": {"paymentToken": ...}})
     (plus a DPoP proof if you bound the token to a key).
  4. 200 -> your result; PAYMENT-RESPONSE carries the AWS Marketplace payment ID.

See https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-process-payment.html
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import boto3
import requests

BASE_URL = os.environ.get("DEEPGRAM_X402_URL", "https://x402.deepgram.com")
AWS_BILLING_INSTRUMENT_ID = "aws.agentcorepayments.awsbilling.v1"


class PaymentError(RuntimeError):
    """The endpoint refused payment, or the 402 had no AWS Billing option."""


@dataclass
class PaidResponse:
    response: requests.Response
    amount_usd: str | None = None
    payment_id: str | None = None
    payment_response: dict[str, Any] = field(default_factory=dict)


def _b64json(value: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(value))


class DeepgramX402Client:
    """Minimal x402 buyer for https://x402.deepgram.com using AgentCore payments (AWS Billing).

    Needs a Payment Manager with an AWS Billing connector and an active payment session
    (see ../setup). The caller needs bedrock-agentcore:ProcessPayment on the manager.
    """

    def __init__(
        self,
        payment_manager_arn: str | None = None,
        payment_session_id: str | None = None,
        user_id: str | None = None,
        region: str | None = None,
        use_dpop: bool | None = None,
        base_url: str = BASE_URL,
        timeout: float = 900,
    ) -> None:
        self.payment_manager_arn = payment_manager_arn or os.environ["PAYMENT_MANAGER_ARN"]
        self.payment_session_id = payment_session_id or os.environ["PAYMENT_SESSION_ID"]
        self.user_id = user_id or os.environ.get("PAYMENT_USER_ID")
        region = region or self.payment_manager_arn.split(":")[3]
        self.payments = boto3.client("bedrock-agentcore", region_name=region)
        self.use_dpop = use_dpop if use_dpop is not None else os.environ.get("USE_DPOP", "1") != "0"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()

    def post(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> PaidResponse:
        """POST to the endpoint, paying the 402 quote once. Raises PaymentError if payment is refused."""
        url = self.base_url + path
        headers = {"Content-Type": content_type} if content_type else {}
        kwargs = {"params": params, "json": json_body, "data": data, "headers": headers, "timeout": self.timeout}

        first = self.http.post(url, **kwargs)
        if first.status_code != 402:
            return PaidResponse(first)  # e.g. 400 for an unsupported parameter; nothing was charged

        header = first.headers.get("PAYMENT-REQUIRED")
        required = _b64json(header) if header else first.json()
        accepted = next((a for a in required.get("accepts", []) if a.get("network") == "aws:base"), None)
        if accepted is None:
            raise PaymentError(f"402 has no aws:base payment option: {required}")

        key = _DpopKey() if self.use_dpop else None
        payment_input: dict[str, Any] = {"version": str(required["x402Version"]), "payload": accepted}
        if key:
            payment_input["options"] = {"dpopJwk": key.public_jwk}

        call: dict[str, Any] = dict(
            paymentManagerArn=self.payment_manager_arn,
            paymentSessionId=self.payment_session_id,
            paymentInstrumentId=AWS_BILLING_INSTRUMENT_ID,
            paymentType="AWS_BILLING_X402",
            paymentInput={"awsBillingX402": payment_input},
            clientToken=str(uuid.uuid4()),  # reuse the same token if you retry ProcessPayment for this quote
        )
        if self.user_id:
            call["userId"] = self.user_id
        payment = self.payments.process_payment(**call)
        token = payment["paymentOutput"]["awsBillingX402"]["paymentToken"]  # a credential: don't log it

        signature = {
            "x402Version": 2,
            "resource": required.get("resource"),
            "accepted": accepted,
            "payload": {"paymentToken": token},
        }
        retry_headers = dict(headers)
        retry_headers["PAYMENT-SIGNATURE"] = base64.b64encode(json.dumps(signature).encode()).decode()
        if key:
            retry_headers["DPoP"] = key.proof("POST", url, token)

        second = self.http.post(url, **{**kwargs, "headers": retry_headers})
        if second.status_code == 402:
            refused = second.headers.get("PAYMENT-REQUIRED")
            reason = _b64json(refused).get("error") if refused else second.text
            raise PaymentError(f"payment refused: {reason}")

        # The quote's `amount` is a decimal USD string (asset iso4217:USD), e.g. "0.000600".
        result = PaidResponse(second, amount_usd=accepted.get("amount"))
        if receipt := second.headers.get("PAYMENT-RESPONSE"):
            result.payment_response = _b64json(receipt)
            result.payment_id = result.payment_response.get("transaction")
        return result


class _DpopKey:
    """Ephemeral P-256 key for RFC 9449 DPoP. Binds the payment token so a leaked token is useless."""

    def __init__(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec

        self._key = ec.generate_private_key(ec.SECP256R1())
        numbers = self._key.public_key().public_numbers()
        self.public_jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url(numbers.x.to_bytes(32, "big")),
            "y": _b64url(numbers.y.to_bytes(32, "big")),
        }

    def proof(self, method: str, url: str, access_token: str) -> str:
        import jwt  # PyJWT

        claims = {
            "jti": str(uuid.uuid4()),
            "htm": method,
            "htu": url.split("?", 1)[0].split("#", 1)[0],
            "iat": int(time.time()),
            "ath": _b64url(hashlib.sha256(access_token.encode()).digest()),
        }
        return jwt.encode(claims, self._key, algorithm="ES256", headers={"typ": "dpop+jwt", "jwk": self.public_jwk})


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
