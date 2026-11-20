"""Speech-to-text for a large file in your own S3 bucket, via a presigned GET URL.

    uv run stt_s3_presigned.py s3://my-bucket/path/meeting.mp3

The URL is fetched by Deepgram, so there is no request-size limit; keep the
expiry longer than the transcription takes.
"""

import sys

import boto3

from deepgram_x402 import DeepgramX402Client

bucket, key = sys.argv[1].removeprefix("s3://").split("/", 1)
presigned = boto3.client("s3").generate_presigned_url(
    "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600
)
paid = DeepgramX402Client().post(
    "/v1/listen", {"model": "nova-3", "smart_format": "true", "diarize": "true"}, json_body={"url": presigned}
)
paid.response.raise_for_status()
print(paid.response.json()["results"]["channels"][0]["alternatives"][0]["transcript"])
print(f"paid ${paid.amount_usd} (payment {paid.payment_id})", file=sys.stderr)
