"""Real reverse-image search providers and evidence retrieval."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup


class ReverseSearchError(RuntimeError):
    """Raised when a remote search cannot be completed."""


USER_AGENT = (
    "consent-media-provenance/0.1 "
    "(reverse-image search; user-requested research tool)"
)


@dataclass(frozen=True)
class SearchMatch:
    """A candidate returned by the remote search provider."""

    title: str
    url: str
    snippet: str
    provider: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _unwrap_result_url(raw_url: str) -> str | None:
    if raw_url.startswith("/"):
        raw_url = f"https://www.google.com{raw_url}"
    parsed = urlparse(raw_url)
    if parsed.path in {"/url", "/imgres"}:
        query = parse_qs(parsed.query)
        for key in ("q", "url"):
            if query.get(key):
                return unquote(query[key][0])
    if parsed.scheme in {"http", "https"}:
        return raw_url
    return None


def _is_source_url(url: str, input_url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    input_host = (urlparse(input_url).hostname or "").lower()
    blocked_hosts = (
        "google.com",
        "googleusercontent.com",
        "gstatic.com",
        "lens.google.com",
    )
    return bool(host) and host != input_host and not any(
        host == blocked or host.endswith(f".{blocked}") for blocked in blocked_hosts
    )


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def search_google_lens(image_url: str, limit: int = 10) -> list[SearchMatch]:
    """Search a publicly reachable image URL through Google Lens.

    The input image itself is never uploaded by this client. The public URL is
    sent to Lens, which is why this provider requires an explicit image URL.
    """

    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReverseSearchError(
            "Google Lens requires --image-url to be a public http(s) image URL"
        )

    lens_url = (
        "https://lens.google.com/uploadbyurl?url="
        f"{quote(image_url, safe='')}"
    )
    try:
        response = requests.get(
            lens_url,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise ReverseSearchError(f"Google Lens request failed: {error}") from error

    soup = BeautifulSoup(response.text, "html.parser")
    matches: list[SearchMatch] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        url = _unwrap_result_url(anchor.get("href", ""))
        if not url or url in seen or not _is_source_url(url, image_url):
            continue
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title:
            title = (urlparse(url).hostname or "discovered page").replace("www.", "")
        parent_text = _clean_text(anchor.parent.get_text(" ", strip=True))
        snippet = parent_text[:400] if parent_text else ""
        matches.append(
            SearchMatch(
                title=title[:240],
                url=url,
                snippet=snippet,
                provider="google-lens",
            )
        )
        seen.add(url)
        if len(matches) >= limit:
            break

    if not matches:
        raise ReverseSearchError(
            "Google Lens returned no external source pages. Try a clearer image or "
            "a different public image URL."
        )
    return matches


def search_serpapi(image_url: str, limit: int = 10) -> list[SearchMatch]:
    """Search Google Lens through SerpApi when SERPAPI_KEY is configured."""

    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise ReverseSearchError(
            "SERPAPI_KEY is required for --provider serpapi; use Google Lens "
            "without a key or configure the key through Replit Secrets."
        )

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_lens",
                "url": image_url,
                "api_key": api_key,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise ReverseSearchError(f"SerpApi request failed: {error}") from error

    matches: list[SearchMatch] = []
    for item in payload.get("visual_matches", [])[:limit]:
        url = item.get("link") or item.get("url")
        if not isinstance(url, str):
            continue
        matches.append(
            SearchMatch(
                title=str(item.get("title") or url),
                url=url,
                snippet=str(item.get("snippet") or ""),
                provider="serpapi-google-lens",
            )
        )

    if not matches:
        raise ReverseSearchError("SerpApi returned no visual matches")
    return matches


def reverse_search(
    image_url: str,
    provider: str = "google-lens",
    limit: int = 10,
) -> list[SearchMatch]:
    if provider == "google-lens":
        return search_google_lens(image_url, limit=limit)
    if provider == "serpapi":
        return search_serpapi(image_url, limit=limit)
    raise ReverseSearchError(f"Unsupported reverse-search provider: {provider}")


def retrieve_evidence(match: SearchMatch) -> dict[str, Any]:
    """Fetch the discovered page and return a hashable evidence envelope."""

    retrieved_at = datetime.now(UTC).isoformat()
    try:
        response = requests.get(
            match.url,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            allow_redirects=True,
        )
        body = response.content
        return {
            "requested_url": match.url,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_bytes": len(body),
            "retrieved_at": retrieved_at,
            "fetch_error": None,
        }
    except requests.RequestException as error:
        return {
            "requested_url": match.url,
            "final_url": None,
            "status_code": None,
            "content_type": None,
            "body_sha256": None,
            "body_bytes": 0,
            "retrieved_at": retrieved_at,
            "fetch_error": str(error),
        }