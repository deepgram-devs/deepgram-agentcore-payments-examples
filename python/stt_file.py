"""Speech-to-text from a local file (raw body, up to ~4.5 MB).

    uv run stt_file.py path/to/audio.wav

For larger files, upload to S3 and pass a presigned URL (see stt_s3_presigned.py).
"""

import mimetypes
import sys
from pathlib import Path

from deepgram_x402 import DeepgramX402Client

path = Path(sys.argv[1])
content_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
paid = DeepgramX402Client().post(
    "/v1/listen", {"model": "nova-3", "smart_format": "true"}, data=path.read_bytes(), content_type=content_type
)
paid.response.raise_for_status()
print(paid.response.json()["results"]["channels"][0]["alternatives"][0]["transcript"])
print(f"paid ${paid.amount_usd} (payment {paid.payment_id})", file=sys.stderr)
