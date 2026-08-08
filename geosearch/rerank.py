"""Second stage: an LLM filters what the vector search retrieved.

The two stages have opposite jobs. FAISS optimises recall - it casts wide and cheaply,
and is happy to return a flood-warning layer for a query about forests because the
abstracts share vocabulary. The LLM optimises precision: it reads the candidates and
throws out the ones that only look related. Neither does the other's job well, which is
why "just raise the similarity floor" is not a substitute - that trades away the recall
we went to FAISS for.

Deliberately the cheap model. This runs on every search, judges 30 short records, and
never writes prose the user sees.

Failure here is never fatal: if Bedrock is unreachable the vector ranking is returned
untouched and flagged, because a degraded search beats a broken one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Sequence

logger = logging.getLogger(__name__)

MODEL_ID = os.environ.get("BEDROCK_SECONDARY_MODEL_ID", "mistral.ministral-3-14b-instruct")
REGION = os.environ.get("BEDROCK_SECONDARY_REGION") or os.environ.get(
    "BEDROCK_REGION", "eu-west-1"
)

# Abstracts run to thousands of characters. The model is judging topical relevance, and
# the first couple of sentences settle that; sending all 30 in full would cost more than
# the search it is refining.
ABSTRACT_CHARS = 300

# Non-greedy, and every match is tried. Greedy matching spanned from the first '[' to the
# last ']' across the whole reply, which is invalid JSON the moment the model answers
# twice - observed live: '[]\n```json\n[]\n```'. Brackets inside prose simply fail to
# parse and are skipped.
_JSON = re.compile(r"\[.*?\]", re.DOTALL)

PROMPT = """You filter search results for a Swiss geodata catalogue.

The user asked for: {query}

Below are {n} candidate datasets found by vector search, which optimises for recall and \
therefore includes near-misses. Decide which ones genuinely answer the request.

{candidates}

Return ONLY a JSON array of the numbers you keep, best first, most relevant to least. \
Drop anything that is merely topically adjacent - a dataset about forest fire prevention \
does not answer a question about forest area. If nothing fits, return [].
Keep at most {top_n}. No prose, no explanation, just the array."""


def _render(candidates: Sequence[dict[str, Any]]) -> str:
    lines = []
    for i, row in enumerate(candidates, 1):
        kind = "vector, queryable" if row.get("queryable") else "raster, display only"
        summary = (row.get("description") or "")[:ABSTRACT_CHARS]
        lines.append(f"{i}. {row.get('title')} [{kind}]\n   {summary}")
    return "\n".join(lines)


class Reranker:
    def __init__(self, model_id: str = MODEL_ID, region: str = REGION) -> None:
        self.model_id = model_id
        self.region = region
        self._client: Any = None

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    connect_timeout=5,
                    # A search the user is waiting on. If the model has not answered in
                    # 20s the vector ranking is the better thing to return.
                    read_timeout=20,
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            )
        return self._client

    async def filter(
        self,
        query: str,
        candidates: Sequence[dict[str, Any]],
        top_n: int = 8,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Returns (kept candidates in the model's order, whether the LLM actually ran)."""
        if not candidates:
            return [], False

        prompt = PROMPT.format(
            query=query,
            n=len(candidates),
            candidates=_render(candidates),
            top_n=top_n,
        )
        try:
            response = await asyncio.to_thread(
                lambda: self._bedrock().converse(
                    modelId=self.model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"maxTokens": 256, "temperature": 0},
                )
            )
            text = "".join(
                block.get("text", "")
                for block in response["output"]["message"]["content"]
            )
        except Exception as exc:
            logger.warning("rerank unavailable (%s); serving vector order", type(exc).__name__)
            return list(candidates[:top_n]), False

        picked = _parse(text, len(candidates))
        if picked is None:
            logger.warning("rerank returned unparseable output; serving vector order")
            return list(candidates[:top_n]), False
        return [candidates[i] for i in picked][:top_n], True


def _parse(text: str, n: int) -> list[int] | None:
    """1-based numbers from the model to 0-based indices, dropping anything out of range.

    An empty array is a real answer - "none of these fit" - and must stay distinguishable
    from a parse failure, so this returns [] there and None only when nothing parsed.
    """
    for match in _JSON.finditer(text):
        try:
            raw = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue  # brackets in prose, e.g. "candidates [1-4]"
        if not isinstance(raw, list):
            continue
        seen: set[int] = set()
        out: list[int] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            idx = value - 1
            if 0 <= idx < n and idx not in seen:
                seen.add(idx)
                out.append(idx)
        return out
    return None
