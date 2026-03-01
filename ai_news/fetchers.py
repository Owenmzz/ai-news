"""Data fetchers and source-spec dispatcher."""

from __future__ import annotations

import html
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

RSS_DEFAULT_URL = "https://news.smol.ai/rss.xml"
GITHUB_TRENDING_BASE_URL = "https://github.com/trending/{language}"
HN_FEED_ENDPOINTS = {
    "top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "best": "https://hacker-news.firebaseio.com/v0/beststories.json",
    "new": "https://hacker-news.firebaseio.com/v0/newstories.json",
}
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
HN_ITEM_WEB_URL = "https://news.ycombinator.com/item?id={item_id}"

DEFAULT_TIMEOUT = 20
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; AI-News-V1-Lite/1.0)"
DEFAULT_HN_AI_HINTS = (
    "ai",
    "llm",
    "gpt",
    "agent",
    "anthropic",
    "openai",
    "copilot",
    "cursor",
    "codex",
    "code assistant",
    "programming",
)


def _headers(user_agent: str | None = None) -> dict[str, str]:
    return {"User-Agent": user_agent or DEFAULT_USER_AGENT}


def _http_get_with_retries(
    url: str,
    timeout: int,
    headers: dict[str, str],
    retries: int = 3,
) -> requests.Response:
    attempts = max(retries, 1)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            response = requests.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts - 1:
                # Exponential backoff to smooth over transient TLS/network failures.
                time.sleep(0.8 * (2 ** attempt))

    assert last_error is not None
    raise last_error


def _clean_text(value: str | None, max_len: int = 800) -> str:
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", html.unescape(value)).strip()
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 1].rstrip() + "..."


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_date_from_link(link: str | None) -> date | None:
    if not link:
        return None

    patterns = [
        r"/issues/(\d{2})-(\d{2})-(\d{2})-",
        r"/issues/(\d{4})-(\d{2})-(\d{2})-",
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if not match:
            continue
        year, month, day = match.groups()
        if len(year) == 2:
            year = f"20{year}"
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    return None


def _parse_rss_entry_datetime(entry: Any) -> datetime | None:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if getattr(entry, "updated_parsed", None):
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

    published = entry.get("published") or entry.get("updated")
    if published:
        try:
            dt = parsedate_to_datetime(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass

    link_date = extract_date_from_link(entry.get("link"))
    if link_date:
        return datetime(link_date.year, link_date.month, link_date.day, tzinfo=timezone.utc)

    return None


def _extract_rss_content(entry: Any) -> str:
    if getattr(entry, "content", None):
        first = entry.content[0] if entry.content else {}
        return _clean_text(first.get("value", ""))
    if getattr(entry, "summary", None):
        return _clean_text(entry.summary)
    return _clean_text(entry.get("description", ""))


def _rss_source_name(link: str | None) -> str:
    if not link:
        return "rss"
    host = urlparse(link).netloc.lower()
    return host or "rss"


def fetch_rss_items(
    target_date: date,
    rss_urls: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    user_agent: str | None = None,
) -> list[dict[str, Any]]:
    urls = rss_urls or [RSS_DEFAULT_URL]
    items: list[dict[str, Any]] = []
    url_errors: list[str] = []
    headers = _headers(user_agent)

    for url in urls:
        try:
            response = _http_get_with_retries(url, timeout=timeout, headers=headers, retries=3)
            feed = feedparser.parse(response.content)
            for entry in feed.entries:
                entry_dt = _parse_rss_entry_datetime(entry)
                entry_date = entry_dt.date() if entry_dt else extract_date_from_link(entry.get("link"))
                if entry_date != target_date:
                    continue

                title = _clean_text(entry.get("title"), max_len=300)
                link = (entry.get("link") or "").strip()
                summary = _extract_rss_content(entry)
                if not title or not link:
                    continue

                source_id = str(entry.get("id") or entry.get("guid") or link)
                items.append(
                    {
                        "source": "rss",
                        "source_name": _rss_source_name(link),
                        "source_id": source_id,
                        "title": title,
                        "url": link,
                        "published_at": _iso_utc(entry_dt or datetime.now(timezone.utc)),
                        "summary": summary,
                        "raw_popularity": {},
                    }
                )
        except Exception as exc:  # noqa: BLE001
            url_errors.append(f"{url}: {exc}")
            continue

    if not items and url_errors:
        raise ValueError("; ".join(url_errors))

    return items


def _to_int(value: str | None) -> int:
    if not value:
        return 0
    number = re.sub(r"[^\d]", "", value)
    return int(number) if number else 0


def fetch_github_trending_items(
    target_date: date,
    languages: list[str] | None = None,
    since: str = "daily",
    timeout: int = DEFAULT_TIMEOUT,
    user_agent: str | None = None,
) -> list[dict[str, Any]]:
    # GitHub Trending does not provide historical snapshots.
    if target_date != datetime.now(timezone.utc).date():
        return []

    langs = languages or ["python", "cpp", "jupyter-notebook"]
    items: list[dict[str, Any]] = []
    now_iso = _iso_utc(datetime.now(timezone.utc))
    headers = _headers(user_agent)

    for lang in langs:
        url = f"{GITHUB_TRENDING_BASE_URL.format(language=lang)}?since={since}"
        response = _http_get_with_retries(url, timeout=timeout, headers=headers, retries=3)

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("article.Box-row")

        for row in rows:
            title_anchor = row.select_one("h2 a")
            if not title_anchor:
                continue

            repo_path = re.sub(r"\s+", "", title_anchor.get("href", "").strip())
            if not repo_path:
                continue

            repo_name = repo_path.strip("/")
            repo_url = f"https://github.com/{repo_name}"
            description_node = row.select_one("p")
            description = _clean_text(description_node.get_text(" ", strip=True) if description_node else "")

            stars_total = 0
            stars_link = row.select_one("a[href$='/stargazers']")
            if stars_link:
                stars_total = _to_int(stars_link.get_text(" ", strip=True))

            stars_today = 0
            stars_today_node = row.select_one("span.d-inline-block.float-sm-right")
            if stars_today_node:
                stars_today = _to_int(stars_today_node.get_text(" ", strip=True))

            items.append(
                {
                    "source": "github",
                    "source_name": "github.com",
                    "source_id": repo_name,
                    "title": repo_name,
                    "url": repo_url,
                    "published_at": now_iso,
                    "summary": description,
                    "raw_popularity": {
                        "stars_total": stars_total,
                        "stars_today": stars_today,
                        "language": lang,
                    },
                }
            )

    return items


def _hn_is_relevant(item: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True

    haystack = " ".join(str(item.get(field, "")) for field in ("title", "text", "url")).lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def fetch_hn_items(
    target_date: date,
    timeout: int = DEFAULT_TIMEOUT,
    max_per_feed: int = 40,
    feed_names: list[str] | None = None,
    keywords: list[str] | None = None,
    require_keyword_match: bool = True,
    user_agent: str | None = None,
) -> list[dict[str, Any]]:
    selected_feeds = feed_names or ["top", "best", "new"]
    combined_ids: list[int] = []
    seen: set[int] = set()
    hint_words = keywords or list(DEFAULT_HN_AI_HINTS)
    headers = _headers(user_agent)

    for feed_name in selected_feeds:
        endpoint = HN_FEED_ENDPOINTS.get(feed_name)
        if not endpoint:
            raise ValueError(f"unsupported hackernews feed: {feed_name}")

        response = _http_get_with_retries(endpoint, timeout=timeout, headers=headers, retries=2)
        ids = response.json()[:max(max_per_feed, 1)]
        for item_id in ids:
            if item_id in seen:
                continue
            combined_ids.append(item_id)
            seen.add(item_id)

    items: list[dict[str, Any]] = []
    for item_id in combined_ids:
        try:
            item_resp = _http_get_with_retries(
                HN_ITEM_URL.format(item_id=item_id),
                timeout=timeout,
                headers=headers,
                retries=1,
            )
        except Exception:  # noqa: BLE001
            continue
        payload = item_resp.json() or {}

        if payload.get("type") != "story":
            continue
        if require_keyword_match and not _hn_is_relevant(payload, hint_words):
            continue

        timestamp = payload.get("time")
        if not timestamp:
            continue

        published_dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        if published_dt.date() != target_date:
            continue

        title = _clean_text(payload.get("title"), max_len=300)
        if not title:
            continue

        story_url = payload.get("url") or HN_ITEM_WEB_URL.format(item_id=item_id)
        summary = _clean_text(payload.get("text"), max_len=500)

        items.append(
            {
                "source": "hn",
                "source_name": "news.ycombinator.com",
                "source_id": str(item_id),
                "title": title,
                "url": story_url,
                "published_at": _iso_utc(published_dt),
                "summary": summary,
                "raw_popularity": {
                    "hn_score": int(payload.get("score") or 0),
                    "hn_comments": int(payload.get("descendants") or 0),
                },
            }
        )

    return items


def _to_list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _resolve_timeout(default_timeout: int, source_spec: Mapping[str, Any]) -> int:
    params = source_spec.get("params") or {}
    try:
        timeout = int(params.get("timeout", default_timeout))
    except (TypeError, ValueError):
        timeout = default_timeout
    return max(timeout, 1)


def fetch_by_source_spec(
    source_spec: Mapping[str, Any],
    target_date: date,
    default_timeout: int = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    source_id = str(source_spec.get("id") or "").strip() or "unknown_source"
    source_type = str(source_spec.get("type") or "").strip().lower()
    params = source_spec.get("params") or {}
    timeout = _resolve_timeout(default_timeout, source_spec)
    user_agent = str(params.get("user_agent") or "").strip() or None

    if source_type == "rss":
        urls = _to_list_str(params.get("urls")) or [RSS_DEFAULT_URL]
        items = fetch_rss_items(
            target_date=target_date,
            rss_urls=urls,
            timeout=timeout,
            user_agent=user_agent,
        )
    elif source_type == "github_trending":
        languages = _to_list_str(params.get("languages")) or ["python", "cpp", "jupyter-notebook"]
        since = str(params.get("since") or "daily")
        items = fetch_github_trending_items(
            target_date=target_date,
            languages=languages,
            since=since,
            timeout=timeout,
            user_agent=user_agent,
        )
    elif source_type == "hackernews":
        feeds = _to_list_str(params.get("feeds")) or ["top", "best", "new"]
        keywords = _to_list_str(params.get("keywords")) or list(DEFAULT_HN_AI_HINTS)
        require_keyword_match = bool(params.get("require_keyword_match", True))
        try:
            max_per_feed = int(params.get("max_per_feed", 40))
        except (TypeError, ValueError):
            max_per_feed = 40
        items = fetch_hn_items(
            target_date=target_date,
            timeout=timeout,
            max_per_feed=max(max_per_feed, 1),
            feed_names=feeds,
            keywords=keywords,
            require_keyword_match=require_keyword_match,
            user_agent=user_agent,
        )
    else:
        raise ValueError(f"unsupported source type: {source_type}")

    for item in items:
        item["source_config_id"] = source_id
        item["source_type"] = source_type
    return items
