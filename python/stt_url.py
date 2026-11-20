"""Speech-to-text from a hosted audio URL (recommended for any file size).

    uv run stt_url.py [AUDIO_URL]
"""

import json
import sys

from deepgram_x402 import DeepgramX402Client

url = sys.argv[1] if len(sys.argv) > 1 else "https://dpgr.am/spacewalk.wav"
client = DeepgramX402Client()
paid = client.post("/v1/listen", {"model": "nova-3", "smart_format": "true"}, json_body={"url": url})
paid.response.raise_for_status()

result = paid.response.json()
print(result["results"]["channels"][0]["alternatives"][0]["transcript"])
print(json.dumps({"paid_usd": paid.amount_usd, "payment_id": paid.payment_id}), file=sys.stderr)
