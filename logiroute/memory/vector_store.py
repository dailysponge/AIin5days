"""Semantic Vector Store and Cosine Similarity Retrieval for Historical Incidents."""

import math
import re
from typing import Any, Dict, List, Tuple


class SemanticVectorStore:
    """Lightweight in-memory and database-backed vector store using TF-IDF term embeddings and cosine similarity."""

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Tokenize text into lowercase alphanumeric tokens."""
        return re.findall(r"\b[a-z0-9_]{2,}\b", text.lower())

    @classmethod
    def create_embedding(cls, text: str) -> Dict[str, float]:
        """Generates a normalized TF term frequency embedding vector."""
        tokens = cls._tokenize(text)
        if not tokens:
            return {}
        
        counts: Dict[str, float] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0.0) + 1.0
            
        # L2 normalize the vector
        norm = math.sqrt(sum(v * v for v in counts.values()))
        if norm > 0:
            return {k: round(v / norm, 4) for k, v in counts.items()}
        return counts

    @classmethod
    def cosine_similarity(cls, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """Computes cosine similarity between two normalized sparse vectors."""
        if not vec1 or not vec2:
            return 0.0
        
        # Dot product of normalized vectors equals cosine similarity
        common_keys = set(vec1.keys()) & set(vec2.keys())
        dot_product = sum(vec1[k] * vec2[k] for k in common_keys)
        return max(0.0, min(1.0, dot_product))

    @classmethod
    def find_top_k(
        cls,
        query_text: str,
        corpus: List[Dict[str, Any]],
        text_key: str = "description",
        top_k: int = 3,
        threshold: float = 0.1,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Finds top-k semantically relevant items from corpus based on cosine similarity."""
        query_vec = cls.create_embedding(query_text)
        scored_items: List[Tuple[Dict[str, Any], float]] = []

        for item in corpus:
            item_text = item.get(text_key, "")
            item_vec = item.get("embedding")
            if not item_vec:
                item_vec = cls.create_embedding(item_text)
            
            score = cls.cosine_similarity(query_vec, item_vec)
            if score >= threshold:
                scored_items.append((item, round(score, 4)))

        scored_items.sort(key=lambda x: x[1], reverse=True)
        return scored_items[:top_k]
