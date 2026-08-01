"""Shard schema — the single envelope shared by all four shard types.

Per Gotcha G5, every shard carries an encryption envelope field and a
provenance pointer from the first commit, even though nothing consumes
them at L0/L1. They cannot be retrofitted into committed history.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SHARD_TYPES = ("facts", "decisions", "gotchas", "artifacts")

_EMPTY_ENVELOPE = {"v": 0, "alg": None, "wrapped_key": None}


@dataclass(frozen=True)
class Shard:
    type: str
    key: str
    body: dict
    created_at: str  # ISO-8601 UTC, supplied by the caller's clock
    tags: tuple[str, ...] = ()
    enc: dict = field(default_factory=lambda: dict(_EMPTY_ENVELOPE))
    provenance: str | None = None  # root CID this shard was forked/inherited from
    v: int = 1

    def __post_init__(self):
        if self.type not in SHARD_TYPES:
            raise ValueError(f"unknown shard type {self.type!r}; must be one of {SHARD_TYPES}")
        if not self.key or not isinstance(self.key, str):
            raise ValueError("shard key must be a non-empty string")

    def to_obj(self) -> dict:
        return {
            "v": self.v,
            "type": self.type,
            "key": self.key,
            "body": self.body,
            "created_at": self.created_at,
            "tags": list(self.tags),
            "enc": self.enc,
            "provenance": self.provenance,
        }

    @staticmethod
    def from_obj(obj: dict) -> "Shard":
        return Shard(
            type=obj["type"],
            key=obj["key"],
            body=obj["body"],
            created_at=obj["created_at"],
            tags=tuple(obj.get("tags", ())),
            enc=obj.get("enc", dict(_EMPTY_ENVELOPE)),
            provenance=obj.get("provenance"),
            v=obj.get("v", 1),
        )
