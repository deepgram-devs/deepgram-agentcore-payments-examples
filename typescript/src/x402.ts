/**
 * Call Deepgram's AWS Marketplace x402 endpoint, paying with Amazon Bedrock AgentCore payments.
 *
 * 1. POST unpaid -> 402 with a base64-JSON PAYMENT-REQUIRED header.
 * 2. Pass the `accepts` entry whose network is "aws:base" UNCHANGED to ProcessPayment
 *    (paymentType AWS_BILLING_X402, instrument aws.agentcorepayments.awsbilling.v1).
 * 3. Retry with PAYMENT-SIGNATURE = base64(JSON {x402Version: 2, resource, accepted, payload: {paymentToken}})
 *    plus a DPoP proof when the token is bound to a key.
 * 4. 200 -> result; PAYMENT-RESPONSE carries the AWS Marketplace payment ID.
 */
import { createHash, randomUUID } from "node:crypto";
import { BedrockAgentCoreClient, ProcessPaymentCommand } from "@aws-sdk/client-bedrock-agentcore";
import { SignJWT, exportJWK, generateKeyPair, type CryptoKey, type JWK } from "jose";

export const BASE_URL = process.env.DEEPGRAM_X402_URL ?? "https://x402.deepgram.com";
const AWS_BILLING_INSTRUMENT_ID = "aws.agentcorepayments.awsbilling.v1";

type Accepted = { network: string; amount?: string; [k: string]: unknown };
type PaymentRequired = { x402Version: number; resource?: unknown; accepts: Accepted[]; error?: string };

export interface PaidResponse {
  response: Response;
  /** Quoted price, a decimal USD string such as "0.000600". */
  amountUsd?: string;
  /** AWS Marketplace payment ID from the PAYMENT-RESPONSE header. */
  paymentId?: string;
}

export interface ClientOptions {
  paymentManagerArn?: string;
  paymentSessionId?: string;
  userId?: string;
  useDpop?: boolean;
}

const b64json = <T>(v: string): T => JSON.parse(Buffer.from(v, "base64").toString("utf8")) as T;

export class DeepgramX402Client {
  private readonly managerArn: string;
  private readonly sessionId: string;
  private readonly userId: string;
  private readonly useDpop: boolean;
  private readonly payments: BedrockAgentCoreClient;

  constructor(opts: ClientOptions = {}) {
    this.managerArn = opts.paymentManagerArn ?? requiredEnv("PAYMENT_MANAGER_ARN");
    this.sessionId = opts.paymentSessionId ?? requiredEnv("PAYMENT_SESSION_ID");
    // Required with IAM authorization; must match the user the session was created for.
    this.userId = opts.userId ?? process.env.PAYMENT_USER_ID ?? "deepgram-example-user";
    this.useDpop = opts.useDpop ?? process.env.USE_DPOP !== "0";
    this.payments = new BedrockAgentCoreClient({ region: this.managerArn.split(":")[3] });
  }

  /** POST to the endpoint, paying the 402 quote once. Throws if the payment is refused. */
  async post(path: string, params: Record<string, string>, body: BodyInit, contentType: string): Promise<PaidResponse> {
    const url = `${BASE_URL}${path}?${new URLSearchParams(params)}`;
    const send = (extra: Record<string, string> = {}) =>
      fetch(url, { method: "POST", headers: { "Content-Type": contentType, ...extra }, body });

    const first = await send();
    if (first.status !== 402) return { response: first }; // e.g. a 400; nothing was charged

    const header = first.headers.get("PAYMENT-REQUIRED");
    const req = header ? b64json<PaymentRequired>(header) : ((await first.json()) as PaymentRequired);
    const accepted = req.accepts.find((a) => a.network === "aws:base");
    if (!accepted) throw new Error(`402 has no aws:base payment option: ${JSON.stringify(req)}`);

    const key = this.useDpop ? await generateKeyPair("ES256") : undefined;
    const publicJwk = key ? await exportJWK(key.publicKey) : undefined;

    const payment = await this.payments.send(
      new ProcessPaymentCommand({
        paymentManagerArn: this.managerArn,
        paymentSessionId: this.sessionId,
        paymentInstrumentId: AWS_BILLING_INSTRUMENT_ID,
        paymentType: "AWS_BILLING_X402",
        userId: this.userId,
        clientToken: randomUUID(), // reuse the same token if you retry ProcessPayment for this quote
        paymentInput: {
          awsBillingX402: {
            version: String(req.x402Version),
            payload: accepted as never, // pass the entry unchanged
            ...(publicJwk
              ? { options: { dpopJwk: { kty: "EC", crv: "P-256", x: publicJwk.x!, y: publicJwk.y! } } }
              : {}),
          },
        },
      }),
    );
    const token = payment.paymentOutput?.awsBillingX402?.paymentToken; // a credential: don't log it
    if (!token) throw new Error("ProcessPayment returned no paymentToken");

    const signature = { x402Version: 2, resource: req.resource, accepted, payload: { paymentToken: token } };
    const headers: Record<string, string> = {
      "PAYMENT-SIGNATURE": Buffer.from(JSON.stringify(signature)).toString("base64"),
    };
    if (key && publicJwk) headers.DPoP = await dpopProof(key.privateKey, publicJwk, "POST", url, token);

    const second = await send(headers);
    if (second.status === 402) {
      const refused = second.headers.get("PAYMENT-REQUIRED");
      throw new Error(`payment refused: ${refused ? b64json<PaymentRequired>(refused).error : await second.text()}`);
    }
    const receipt = second.headers.get("PAYMENT-RESPONSE");
    return {
      response: second,
      amountUsd: accepted.amount,
      paymentId: receipt ? b64json<{ transaction?: string }>(receipt).transaction : undefined,
    };
  }
}

/** RFC 9449 DPoP proof bound to this method + URL (no query) and to the payment token (ath). */
async function dpopProof(privateKey: CryptoKey, jwk: JWK, method: string, url: string, token: string): Promise<string> {
  return new SignJWT({
    htm: method,
    htu: url.split(/[?#]/)[0],
    ath: createHash("sha256").update(token).digest("base64url"),
  })
    .setProtectedHeader({ typ: "dpop+jwt", alg: "ES256", jwk: { kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y } })
    .setJti(randomUUID())
    .setIssuedAt()
    .sign(privateKey);
}

function requiredEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`set ${name}`);
  return v;
}
