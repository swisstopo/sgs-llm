#!/usr/bin/env python3
"""Call the pilot's Bedrock models from a workstation with a Bedrock API key.

Setup (once):
    pip install -U boto3           # bearer-token support needs a 2025+ boto3
    export AWS_BEARER_TOKEN_BEDROCK=<key>   # ask the project admin; VPN required

Usage:
    python scripts/ask-llm.py "Nenne drei Schweizer Kantone."
    python scripts/ask-llm.py                     # interactive chat, Ctrl-D ends

The key only permits model inference and only from the project's fixed
developer network (docs/deployment.md#use-the-models-from-a-workstation) —
off-VPN calls fail with AccessDenied. Model and region default to the pilot's
working secondary model; the primary Claude profile stays blocked until the
organization SCP is amended (docs/llm.md).
"""

import os
import sys

import boto3

MODEL_ID = os.environ.get("SGS_LLM_MODEL", "mistral.ministral-3-14b-instruct")
REGION = os.environ.get("SGS_LLM_REGION", "eu-west-1")


def main() -> None:
    if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        sys.exit("AWS_BEARER_TOKEN_BEDROCK is not set — see the header of this script.")

    client = boto3.client("bedrock-runtime", region_name=REGION)
    messages = []

    def turn(text: str) -> str:
        messages.append({"role": "user", "content": [{"text": text}]})
        response = client.converse(
            modelId=MODEL_ID,
            messages=messages,
            inferenceConfig={"maxTokens": 1024},
        )
        reply = response["output"]["message"]
        messages.append(reply)
        return "".join(block.get("text", "") for block in reply["content"])

    if len(sys.argv) > 1:
        print(turn(" ".join(sys.argv[1:])))
        return

    print(f"[{MODEL_ID} @ {REGION} — empty line or Ctrl-D to quit]")
    while True:
        try:
            prompt = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            break
        print(turn(prompt))


if __name__ == "__main__":
    main()
