"""Framework-agnostic Deepgram tools that pay per call via AgentCore payments (AWS Billing).

Each call spends from the payment session's budget; the session spend limit caps
what the agent can spend in total.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache

from deepgram_x402 import DeepgramX402Client


@lru_cache(maxsize=1)
def _client() -> DeepgramX402Client:
    return DeepgramX402Client()


def transcribe_audio_url(audio_url: str, diarize: bool = False) -> str:
    """Transcribe speech in a publicly fetchable (or presigned) audio URL with Deepgram nova-3.

    Costs $0.004333 per audio minute, billed to the AWS account through AWS Marketplace.
    """
    params = {"model": "nova-3", "smart_format": "true"}
    if diarize:
        params["diarize"] = "true"
    paid = _client().post("/v1/listen", params, json_body={"url": audio_url})
    if not paid.response.ok:
        return f"Deepgram error {paid.response.status_code}: {paid.response.text[:500]}"
    transcript = paid.response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
    return f"{transcript}\n\n[paid ${paid.amount_usd}, AWS Marketplace payment {paid.payment_id}]"


def synthesize_speech(text: str, voice: str = "flux-haley-en") -> str:
    """Turn text into speech with Deepgram Flux TTS (voice `flux-{name}-{lang}`) or Aura-2 (`aura-2-{name}-{lang}`).

    Flux TTS costs $0.045 and Aura-2 $0.03 per 1,000 characters. Returns the path of the MP3 written.
    """
    path = "/v1/speak" if voice.startswith("aura-") else "/v2/speak"
    paid = _client().post(path, {"model": voice}, json_body={"text": text})
    if not paid.response.ok:
        return f"Deepgram error {paid.response.status_code}: {paid.response.text[:500]}"
    out_dir = os.environ.get("AUDIO_OUT_DIR", tempfile.gettempdir())
    out = os.path.join(out_dir, f"deepgram-{paid.payment_id or 'speech'}.mp3")
    with open(out, "wb") as f:
        f.write(paid.response.content)
    return f"Wrote {out} [paid ${paid.amount_usd}, AWS Marketplace payment {paid.payment_id}]"
