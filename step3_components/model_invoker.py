"""Reusable component #2 - Model invoker.

Uses the Bedrock *Converse* API, which gives one request/response format for
every model (Nova, Claude, Llama, Mistral ...), so swapping models is just a
different model ID. The course snippet used the legacy `invoke_model` +
Claude v2 text-completion format, which newer models do not accept.

Features: retries with exponential backoff on throttling, latency + token
metrics, optional document attachments (PDF/DOCX), embeddings, and a
deterministic MOCK mode for offline testing.
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import mock_bedrock  # noqa: E402


@dataclass
class ModelResponse:
    """Model output plus latency, token usage and stop reason."""
    model_id: str
    text: str
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""

    @property
    def est_cost_usd(self) -> float | None:
        """Estimated cost of this call from config.PRICING_PER_1K, or None if unknown."""
        price = config.price_for(self.model_id)
        if not price:
            return None
        return self.input_tokens / 1000 * price[0] + self.output_tokens / 1000 * price[1]


RETRYABLE = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelNotReadyException",
    "InternalServerException",
    "ModelTimeoutException",
}


class ModelInvoker:
    """One interface for calling any Bedrock model, with retries and metrics."""
    def __init__(self, region: str = config.REGION, mock: bool = config.MOCK_MODE,
                 max_retries: int = 2):
        self.mock = mock
        self.max_retries = max_retries
        self._client = None
        self.region = region

    @property
    def client(self):
        """Lazily created bedrock-runtime client."""
        if self._client is None:
            if self.region == config.REGION:
                self._client = config.bedrock_runtime()  # shared, adaptive retries
            else:
                import boto3
                from botocore.config import Config
                self._client = boto3.client(
                    "bedrock-runtime", region_name=self.region,
                    config=Config(read_timeout=120, retries={"mode": "adaptive", "max_attempts": 10}))
        return self._client

    # ------------------------------------------------------------------ text
    def invoke(self, model_id: str, prompt: str, system: str | None = None,
               temperature: float = 0.0, max_tokens: int = 1000,
               document: tuple[str, str, bytes] | None = None) -> ModelResponse:
        """Invoke a chat model.

        document: optional (name, format, bytes) attachment, format one of
        pdf | csv | doc | docx | xls | xlsx | html | txt | md.
        """
        if self.mock:
            r = mock_bedrock.mock_converse(model_id, prompt, system)
            return ModelResponse(model_id, r.text, r.latency_s, r.input_tokens,
                                 r.output_tokens, r.stop_reason)

        content: list[dict] = []
        if document:
            name, fmt, data = document
            safe_name = re.sub(r"[^A-Za-z0-9 \-()\[\]]", "-", name)[:200] or "document"
            content.append({"document": {"name": safe_name, "format": fmt, "source": {"bytes": data}}})
        content.append({"text": prompt})

        kwargs = {
            "modelId": model_id,
            "messages": [{"role": "user", "content": content}],
            "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}]

        start = time.perf_counter()
        resp = self._with_retries(lambda: self.client.converse(**kwargs))
        latency = time.perf_counter() - start

        text = "".join(
            block.get("text", "") for block in resp["output"]["message"]["content"]
        )
        usage = resp.get("usage", {})
        return ModelResponse(
            model_id=model_id,
            text=text.strip(),
            latency_s=latency,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            stop_reason=resp.get("stopReason", ""),
        )

    def invoke_template(self, template_manager, template_name: str, model_id: str,
                        document=None, **variables) -> ModelResponse:
        """Render a prompt template and invoke the model with that template's settings."""
        system, user, t = template_manager.render(template_name, **variables)
        return self.invoke(model_id, user, system=system, temperature=t.temperature,
                           max_tokens=t.max_tokens, document=document)

    # ------------------------------------------------------------ embeddings
    def embed(self, text: str, model_id: str = config.EMBEDDING_MODEL) -> list[float]:
        """Return a Titan embedding vector for the text."""
        if self.mock:
            return mock_bedrock.mock_embedding(text)
        body = json.dumps({"inputText": text[:8000], "dimensions": 512, "normalize": True})
        resp = self._with_retries(
            lambda: self.client.invoke_model(modelId=model_id, body=body)
        )
        return json.loads(resp["body"].read())["embedding"]

    # --------------------------------------------------------------- helpers
    def _with_retries(self, fn):
        if self.max_retries:
            return config.call_with_backoff(fn, what="Bedrock call")
        from botocore.exceptions import ClientError

        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code not in RETRYABLE or attempt == self.max_retries:
                    raise
                time.sleep(min(2 ** attempt * 2 + random.random(), 30))
