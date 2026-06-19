from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8765"


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    request = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot connect to Memory Loom backend: {exc.reason}") from exc

    if not raw:
        return None
    return json.loads(raw)


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def health(args: argparse.Namespace) -> None:
    print_json(request_json("GET", f"{args.base_url}/health"))


def ingest(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {
        "source": args.source,
        "content": args.content,
        "app_name": args.app_name,
        "window_title": args.window_title,
        "metadata": {"kind": args.kind},
    }
    print_json(request_json("POST", f"{args.base_url}/ingest", payload))


def search(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {
        "query": args.query,
        "top_k": args.top_k,
        "backend": args.backend,
    }
    print_json(request_json("POST", f"{args.base_url}/search", payload))


def embed_now(args: argparse.Namespace) -> None:
    url = f"{args.base_url}/admin/embed-now"
    if args.retry_failed:
        url = f"{url}?retry_failed=true"
    print_json(request_json("POST", url))


def rebuild_vector_index(args: argparse.Namespace) -> None:
    print_json(request_json("POST", f"{args.base_url}/admin/rebuild-vector-index"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Memory Loom backend API client.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    subparsers = parser.add_subparsers(required=True)

    health_parser = subparsers.add_parser("health", help="Check backend health.")
    health_parser.set_defaults(func=health)

    ingest_parser = subparsers.add_parser("ingest", help="Insert a memory event.")
    ingest_parser.add_argument("--content", required=True)
    ingest_parser.add_argument("--source", default="manual")
    ingest_parser.add_argument("--app-name", default="PythonClient")
    ingest_parser.add_argument("--window-title", default="Memory Loom API Client")
    ingest_parser.add_argument("--kind", default="manual-test")
    ingest_parser.set_defaults(func=ingest)

    search_parser = subparsers.add_parser("search", help="Search memory events.")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument(
        "--backend",
        choices=["hybrid", "keyword", "vector"],
        default="hybrid",
    )
    search_parser.set_defaults(func=search)

    embed_parser = subparsers.add_parser("embed-now", help="Run one embedding batch.")
    embed_parser.add_argument("--retry-failed", action="store_true")
    embed_parser.set_defaults(func=embed_now)

    rebuild_parser = subparsers.add_parser(
        "rebuild-vector-index",
        help="Drop and rebuild the LanceDB vector index from SQLite events.",
    )
    rebuild_parser.set_defaults(func=rebuild_vector_index)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
