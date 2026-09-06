"""Command-line entry point for the media provenance pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .chain import append_anchor, verify_chain, verify_evidence
from .face import FaceProcessingError, detect_and_encode
from .reverse_search import (
    ReverseSearchError,
    retrieve_evidence,
    reverse_search,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def run_pipeline(args: argparse.Namespace) -> int:
    observation = detect_and_encode(args.image)
    matches = reverse_search(
        args.image_url,
        provider=args.provider,
        limit=args.limit,
    )
    selected = matches[0]
    fetched = retrieve_evidence(selected)
    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{run_stamp}-{observation.image_sha256[:10]}"
    run_dir = Path(args.output_dir) / run_id

    search_record = {
        "provider": args.provider,
        "searched_image_url": args.image_url,
        "searched_at": datetime.now(UTC).isoformat(),
        "matches": [match.as_dict() for match in matches],
        "selected_match": selected.as_dict(),
    }
    evidence = {
        "pipeline_version": "0.1.0",
        "run_id": run_id,
        "input": {
            "local_path": str(Path(args.image).expanduser().resolve()),
            "public_image_url": args.image_url,
            "image_sha256": observation.image_sha256,
        },
        "face_observation": observation.as_dict(),
        "reverse_search": search_record,
        "discovered_page": {
            "match": selected.as_dict(),
            "retrieval": fetched,
        },
    }

    _write_json(run_dir / "face.json", observation.as_dict())
    _write_json(run_dir / "search.json", search_record)
    _write_json(run_dir / "evidence.json", evidence)
    block = append_anchor(
        args.chain,
        evidence_file=str(run_dir / "evidence.json"),
        evidence=evidence,
        source_url=selected.url,
    )

    print(f"run_id: {run_id}")
    print(f"face: detected {observation.face_count} face(s), encoded locally")
    print(f"search: {len(matches)} candidate page(s) from {args.provider}")
    print(f"match: {selected.title} — {selected.url}")
    print(f"evidence: {run_dir / 'evidence.json'}")
    print(f"chain block: {block['index']} ({block['block_hash']})")
    print(f"chain file: {args.chain}")
    return 0


def verify_pipeline(args: argparse.Namespace) -> int:
    if args.evidence:
        result = verify_evidence(args.chain, args.evidence, args.block)
    else:
        result = verify_chain(args.chain)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] and result.get("evidence_match", True) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-provenance",
        description=(
            "Detect and locally encode a face, reverse-search the same media, "
            "and anchor the discovered page in a verifiable local chain."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run all three pipeline stages")
    run.add_argument("--image", required=True, help="local input image")
    run.add_argument(
        "--image-url",
        required=True,
        help="public URL for the same image; sent to the reverse-search provider",
    )
    run.add_argument(
        "--provider",
        choices=("google-lens", "serpapi"),
        default="google-lens",
        help="real reverse-image search provider",
    )
    run.add_argument("--limit", type=int, default=10)
    run.add_argument("--chain", default="chain/chain.json")
    run.add_argument("--output-dir", default="runs")
    run.set_defaults(handler=run_pipeline)

    verify = commands.add_parser(
        "verify",
        help="verify chain links and optionally match an evidence file",
    )
    verify.add_argument("--chain", default="chain/chain.json")
    verify.add_argument("--evidence")
    verify.add_argument("--block", type=int)
    verify.set_defaults(handler=verify_pipeline)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (FaceProcessingError, ReverseSearchError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())