"""Step 2.4 - Simple RAG component using policy information.

1. Load policy documents from S3 (policies/ prefix)
2. Chunk them by "## [Section x.y]" heading
3. Embed each chunk with Amazon Titan Text Embeddings V2
4. At query time: filter chunks to the claim's policy product (AUTO/HOME/HLT
   from the policy-number prefix), embed the query, rank by cosine similarity.

The vector index is a small in-memory list cached to .rag_index.json - enough
for a PoC. For production, swap in Amazon Bedrock Knowledge Bases (managed
chunking/embedding + OpenSearch Serverless or S3 Vectors) - see extras/.

  python step2_poc/policy_rag.py "water leak under sink for weeks" --policy HOME-2024-118902
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import mock_bedrock  # noqa: E402
from step2_poc.s3_storage import DocumentStore  # noqa: E402

INDEX_FILE = config.PROJECT_ROOT / (".rag_index_mock.json" if config.MOCK_MODE else ".rag_index.json")


def embed(text: str) -> list[float]:
    """Embed text with Titan Text Embeddings V2 (or the mock embedding offline)."""
    if config.MOCK_MODE:
        return mock_bedrock.mock_embedding(text)
    resp = config.call_with_backoff(lambda: config.bedrock_runtime().invoke_model(
        modelId=config.EMBEDDING_MODEL,
        body=json.dumps({"inputText": text[:8000], "dimensions": 512, "normalize": True}),
    ), what="embedding")
    return json.loads(resp["body"].read())["embedding"]


def cosine(a, b) -> float:
    """Cosine similarity of two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunk_policy(name: str, text: str) -> list[dict]:
    """Split a policy document into one chunk per '## [Section x.y]' heading."""
    m = re.search(r"policy prefix (\w+)", text)
    product = m.group(1) if m else name.split("_")[-1].split(".")[0]
    chunks = []
    for part in re.split(r"\n(?=## )", text):
        h = re.match(r"## (\[Section [\d.]+\])\s*(.*)", part)
        if not h:
            continue
        chunks.append({
            "source": name,
            "product": product,
            "section": h.group(1),
            "title": h.group(2).strip(),
            "text": part.strip(),
        })
    return chunks


class PolicyKnowledgeBase:
    """In-memory vector index over policy sections, with a product filter."""
    def __init__(self, store: DocumentStore | None = None):
        self.store = store or DocumentStore()
        self.chunks: list[dict] = []

    def build(self, force: bool = False) -> "PolicyKnowledgeBase":
        """Load policies from S3 and embed them, reusing the cached index if nothing changed."""
        keys = [k for k in self.store.list_keys(config.POLICIES_PREFIX) if k.endswith((".md", ".txt"))]
        if not keys:
            raise RuntimeError(
                f"No policies found in s3://{self.store.bucket}/{config.POLICIES_PREFIX}. "
                "Run: python step2_poc/upload_documents.py "
                "(use the same MOCK_MODE setting as this command; check .env)")
        if INDEX_FILE.exists() and not force:
            cached = json.loads(INDEX_FILE.read_text())
            if cached.get("keys") == keys and cached.get("model") == config.EMBEDDING_MODEL:
                self.chunks = cached["chunks"]
                return self
        self.chunks = []
        for key in keys:
            text = self.store.get_bytes(key).decode("utf-8")
            self.chunks += chunk_policy(Path(key).name, text)
        if not config.MOCK_MODE:
            print(f"Building policy index: embedding {len(self.chunks)} sections with "
                  f"{config.EMBEDDING_MODEL} (one-time, cached in {INDEX_FILE.name}) ...")
        for i, c in enumerate(self.chunks):
            if i and not config.MOCK_MODE:
                time.sleep(config.EMBED_DELAY_S)
            c["embedding"] = embed(c["text"])
        INDEX_FILE.write_text(json.dumps({"keys": keys, "model": config.EMBEDDING_MODEL,
                                          "chunks": self.chunks}))
        return self

    def retrieve(self, query: str, policy_number: str | None = None, k: int = 4) -> list[dict]:
        """Return the k most similar sections, filtered to the claim's policy product."""
        if not self.chunks:
            self.build()
        candidates = self.chunks
        if policy_number:
            prefix = policy_number.split("-")[0].upper()
            filtered = [c for c in self.chunks if c["product"].upper() == prefix]
            candidates = filtered or self.chunks  # metadata filter, fall back to all
        q = embed(query)
        scored = sorted(({**c, "score": cosine(q, c["embedding"])} for c in candidates),
                        key=lambda c: c["score"], reverse=True)
        return [{k_: v for k_, v in c.items() if k_ != "embedding"} for c in scored[:k]]

    @staticmethod
    def format_context(hits: list[dict]) -> str:
        """Format retrieved sections as prompt context."""
        if not hits:
            return "(no relevant policy excerpts found)"
        return "\n\n".join(f"{h['text']}\n(source: {h['source']}, relevance {h['score']:.2f})" for h in hits)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--policy", help="policy number, used to filter by product")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    kb = PolicyKnowledgeBase().build(force=a.rebuild)
    for h in kb.retrieve(a.query, a.policy):
        print(f"{h['score']:.3f}  {h['section']} {h['title']}  ({h['source']})")
