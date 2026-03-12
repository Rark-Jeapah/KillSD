"""Near-duplicate fingerprints for distilled items."""

from __future__ import annotations

import re
from hashlib import blake2b, sha1

from pydantic import Field

from src.core.schemas import StrictModel
from src.distill.item_card_schema import ItemCard, unique_preserve_order


TOKEN_PATTERN = re.compile(r"[\w]+", flags=re.UNICODE)


class ItemFingerprint(StrictModel):
    """Fingerprint payload for one item card."""

    fingerprint_id: str
    source_item_id: str
    card_id: str
    topic: str
    normalized_text: str
    token_signature: list[str] = Field(default_factory=list)
    shingle_signature: list[str] = Field(default_factory=list)
    simhash64: str
    concept_signature: list[str] = Field(default_factory=list)


class NearDuplicateCandidate(StrictModel):
    """Potential near-duplicate pair between two source items."""

    left_source_item_id: str
    right_source_item_id: str
    left_card_id: str
    right_card_id: str
    hamming_distance: int
    jaccard_similarity: float
    shared_tokens: list[str] = Field(default_factory=list)


def normalize_text(text: str) -> str:
    """Normalize text for fingerprint generation."""
    tokens = TOKEN_PATTERN.findall(text.lower())
    return " ".join(tokens)


def _hash_hex(text: str, *, size: int = 8) -> str:
    return blake2b(text.encode("utf-8"), digest_size=size).hexdigest()


def _build_shingles(tokens: list[str], width: int = 3) -> list[str]:
    if len(tokens) <= width:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[index : index + width]) for index in range(len(tokens) - width + 1)]


def _simhash(tokens: list[str]) -> int:
    """Compute a simple 64-bit simhash from normalized tokens."""
    vector = [0] * 64
    for token in tokens:
        token_hash = int.from_bytes(
            blake2b(token.encode("utf-8"), digest_size=8).digest(), byteorder="big"
        )
        for bit_index in range(64):
            bit = 1 if (token_hash >> bit_index) & 1 else -1
            vector[bit_index] += bit

    result = 0
    for bit_index, value in enumerate(vector):
        if value >= 0:
            result |= 1 << bit_index
    return result


def hamming_distance(left: int, right: int) -> int:
    """Return the bit distance between two 64-bit integers."""
    return (left ^ right).bit_count()


def build_item_fingerprint(item_card: ItemCard) -> ItemFingerprint:
    """Create a near-duplicate fingerprint from an item card."""
    normalized_text = normalize_text(
        " ".join(
            [
                item_card.topic,
                item_card.stem,
                " ".join(item_card.canonical_moves),
                " ".join(item_card.trigger_patterns),
            ]
        )
    )
    tokens = unique_preserve_order(TOKEN_PATTERN.findall(normalized_text))
    shingles = _build_shingles(tokens)
    simhash = _simhash(tokens)
    seed = f"{item_card.source_item_id}:{normalized_text}:{item_card.topic}"
    return ItemFingerprint(
        fingerprint_id=f"fp-{sha1(seed.encode('utf-8')).hexdigest()[:12]}",
        source_item_id=item_card.source_item_id,
        card_id=item_card.card_id,
        topic=item_card.topic,
        normalized_text=normalized_text,
        token_signature=tokens[:24],
        shingle_signature=[_hash_hex(shingle, size=6) for shingle in shingles[:24]],
        simhash64=f"{simhash:016x}",
        concept_signature=unique_preserve_order(
            [item_card.subject_area, item_card.topic] + item_card.subtopics + item_card.diagram_tags
        ),
    )


def detect_near_duplicates(
    fingerprints: list[ItemFingerprint], *, max_hamming_distance: int = 12, min_jaccard: float = 0.35
) -> list[NearDuplicateCandidate]:
    """Find candidate near-duplicate pairs by simhash and token overlap."""
    candidates: list[NearDuplicateCandidate] = []
    for index, left in enumerate(fingerprints):
        for right in fingerprints[index + 1 :]:
            left_tokens = set(left.token_signature)
            right_tokens = set(right.token_signature)
            union = left_tokens | right_tokens
            if not union:
                continue
            shared = sorted(left_tokens & right_tokens)
            jaccard = len(shared) / len(union)
            distance = hamming_distance(int(left.simhash64, 16), int(right.simhash64, 16))
            if distance <= max_hamming_distance or jaccard >= min_jaccard:
                candidates.append(
                    NearDuplicateCandidate(
                        left_source_item_id=left.source_item_id,
                        right_source_item_id=right.source_item_id,
                        left_card_id=left.card_id,
                        right_card_id=right.card_id,
                        hamming_distance=distance,
                        jaccard_similarity=round(jaccard, 4),
                        shared_tokens=shared[:12],
                    )
                )
    return sorted(candidates, key=lambda item: (item.hamming_distance, -item.jaccard_similarity))
