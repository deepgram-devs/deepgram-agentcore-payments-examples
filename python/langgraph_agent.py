"""A LangGraph (LangChain create_agent) agent that pays Deepgram per call with AWS Billing.

    uv run --extra langgraph langgraph_agent.py "Say 'your order has shipped' in a friendly voice."

The AgentCore payments LangGraph middleware (bedrock-agentcore[langgraph]) currently pays
stablecoin (CRYPTO_X402) quotes only, so the tools here call ProcessPayment with
AWS_BILLING_X402 directly via deepgram_x402.py.
"""

import os
import sys

from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
from langchain_core.tools import tool

import deepgram_tools

agent = create_agent(
    model=ChatBedrockConverse(model=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")),
    tools=[tool(deepgram_tools.transcribe_audio_url), tool(deepgram_tools.synthesize_speech)],
    system_prompt="You can transcribe audio and generate speech with Deepgram. Each tool call costs money; "
    "call a tool only when the user's request needs it, and tell the user what it cost.",
)

prompt = " ".join(sys.argv[1:]) or "Transcribe https://dpgr.am/spacewalk.wav and summarize it in one sentence."
result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
print(result["messages"][-1].content)
