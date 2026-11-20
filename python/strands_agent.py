"""A Strands agent that can transcribe and speak, paying Deepgram per call with AWS Billing.

    uv run --extra strands strands_agent.py "Transcribe https://dpgr.am/spacewalk.wav and summarize it in one sentence."

The AgentCore payments Strands plugin (bedrock-agentcore[strands-agents]) currently pays
stablecoin (CRYPTO_X402) quotes only, so the tools here call ProcessPayment with
AWS_BILLING_X402 directly via deepgram_x402.py.
"""

import os
import sys

from strands import Agent, tool
from strands.models import BedrockModel

import deepgram_tools

agent = Agent(
    model=BedrockModel(model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")),
    system_prompt="You can transcribe audio and generate speech with Deepgram. Each tool call costs money; "
    "call a tool only when the user's request needs it, and tell the user what it cost.",
    tools=[tool(deepgram_tools.transcribe_audio_url), tool(deepgram_tools.synthesize_speech)],
)

prompt = " ".join(sys.argv[1:]) or "Transcribe https://dpgr.am/spacewalk.wav and summarize it in one sentence."
agent(prompt)
