"""A small append-only local chain for tamper-evident evidence anchoring."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def evidence_hash(evidence: dict[str, Any]) -> str:
    return sha256_text(canonical_json(evidence))


def _block_hash(block: dict[str, Any]) -> str:
    unsigned = {
        "index": block["index"],
        "timestamp": block["timestamp"],
        "previous_hash": block["previous_hash"],
        "payload": block["payload"],
    }
    return sha256_text(canonical_json(unsigned))


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
            json.dump(value, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_chain(chain_path: str | Path) -> list[dict[str, Any]]:
    path = Path(chain_path)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Chain file is not valid JSON: {path}") from error
    if not isinstance(value, list):
        raise ValueError("Chain file must contain a JSON array")
    return value


def append_anchor(
    chain_path: str | Path,
    *,
    evidence_file: str,
    evidence: dict[str, Any],
    source_url: str,
) -> dict[str, Any]:
    """Append an evidence anchor and return the newly created block."""

    path = Path(chain_path)
    chain = read_chain(path)
    previous_hash = chain[-1]["block_hash"] if chain else GENESIS_HASH
    block = {
        "index": len(chain),
        "timestamp": datetime.now(UTC).isoformat(),
        "previous_hash": previous_hash,
        "payload": {
            "type": "media-provenance-anchor",
            "evidence_file": evidence_file,
            "evidence_sha256": evidence_hash(evidence),
            "source_url": source_url,
        },
    }
    block["block_hash"] = _block_hash(block)
    _write_atomic(path, [*chain, block])
    return block


def verify_chain(chain_path: str | Path) -> dict[str, Any]:
    """Verify every link and digest in the local chain."""

    chain = read_chain(chain_path)
    previous_hash = GENESIS_HASH
    for expected_index, block in enumerate(chain):
        if block.get("index") != expected_index:
            return {
                "valid": False,
                "reason": f"block index mismatch at position {expected_index}",
                "checked_blocks": expected_index,
            }
        if block.get("previous_hash") != previous_hash:
            return {
                "valid": False,
                "reason": f"previous hash mismatch at block {expected_index}",
                "checked_blocks": expected_index,
            }
        if block.get("block_hash") != _block_hash(block):
            return {
                "valid": False,
                "reason": f"block hash mismatch at block {expected_index}",
                "checked_blocks": expected_index,
            }
        previous_hash = block["block_hash"]
    return {"valid": True, "reason": None, "checked_blocks": len(chain)}


def verify_evidence(
    chain_path: str | Path,
    evidence_path: str | Path,
    block_index: int | None = None,
) -> dict[str, Any]:
    chain_result = verify_chain(chain_path)
    if not chain_result["valid"]:
        return {**chain_result, "evidence_match": False}

    chain = read_chain(chain_path)
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    digest = evidence_hash(evidence)
    candidates = [
        block
        for block in chain
        if block.get("payload", {}).get("evidence_sha256") == digest
    ]
    if block_index is not None:
        candidates = [
            block for block in candidates if block.get("index") == block_index
        ]
    return {
        **chain_result,
        "evidence_match": bool(candidates),
        "evidence_sha256": digest,
        "matching_blocks": [block["index"] for block in candidates],
    }