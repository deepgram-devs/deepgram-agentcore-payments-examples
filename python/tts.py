"""Text-to-speech with Flux TTS (/v2/speak) or Aura-2 (/v1/speak).

    uv run tts.py "Your appointment is confirmed for 3pm tomorrow." [flux-haley-en | aura-2-thalia-en]
"""

import sys

from deepgram_x402 import DeepgramX402Client

text = sys.argv[1] if len(sys.argv) > 1 else "Hello from Deepgram."
model = sys.argv[2] if len(sys.argv) > 2 else "flux-haley-en"
path = "/v2/speak" if model.startswith("flux-") else "/v1/speak"

paid = DeepgramX402Client().post(path, {"model": model}, json_body={"text": text})
paid.response.raise_for_status()
with open("speech.mp3", "wb") as f:
    f.write(paid.response.content)
print(f"wrote speech.mp3 ({len(paid.response.content)} bytes); paid ${paid.amount_usd} (payment {paid.payment_id})")
