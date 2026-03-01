"""Normalization, deduplication, scoring, and output helpers."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCE_WEIGHTS = {
    "rss": 34.0,
    "github": 28.0,
    "hn": 24.0,
}

KEYWORD_GROUPS = {
    "core": [
        "ai coding",
        "code assistant",
        "code generation",
        "coding agent",
        "agentic coding",
    ],
    "tools": [
        "copilot",
        "cursor",
        "claude code",
        "codex",
        "aider",
        "cline",
        "continue",
    ],
    "mechanism": [
        "mcp",
        "rag for code",
        "repo indexing",
        "tool calling",
        "function calling",
    ],
    "engineering": [
        "code review",
        "test generation",
        "bug fix",
        "refactor",
        "pr automation",
    ],
    "zh": [
        "ai编程",
        "代码助手",
        "智能编码",
        "自动化测试",
        "代码审查",
    ],
}

GROUP_WEIGHTS = {
    "core": 5.0,
    "tools": 4.0,
    "mechanism": 3.0,
    "engineering": 3.0,
    "zh": 4.0,
}

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"spm", "from", "ref", "source", "fbclid", "gclid", "si"}
SOURCE_LABELS = {
    "rss": "RSS",
    "github": "GitHub",
    "hn": "Hacker News",
}


def _parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonicalize_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    filtered_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith(TRACKING_PARAM_PREFIXES):
            continue
        if lowered in TRACKING_PARAMS:
            continue
        filtered_query.append((key, value))

    path = parsed.path.rstrip("/")
    if not path:
        path = "/"

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def normalize_title(title: str) -> str:
    if not title:
        return ""
    text = html.unescape(title)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _domain_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.netloc.lower()


def _build_content_hash(source_id: str, title_norm: str, canonical_url: str) -> str:
    payload = "|".join([title_norm.lower(), _domain_from_url(canonical_url), source_id])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _keyword_score(text: str) -> tuple[float, list[str]]:
    lowered = text.lower()
    score = 0.0
    matched: list[str] = []

    for group, keywords in KEYWORD_GROUPS.items():
        for keyword in keywords:
            if keyword.lower() in lowered:
                matched.append(keyword)
                score += GROUP_WEIGHTS[group]

    unique_matched = sorted(set(matched))
    return min(score, 25.0), unique_matched


def _popularity_score(item: dict[str, Any]) -> float:
    popularity = item.get("raw_popularity") or {}
    source = item.get("source", "")

    if source == "github":
        stars_today = float(popularity.get("stars_today") or 0)
        stars_total = float(popularity.get("stars_total") or 0)
        score = stars_today / 25.0 + stars_total / 50000.0
        return min(score, 20.0)

    if source == "hn":
        hn_score = float(popularity.get("hn_score") or 0)
        comments = float(popularity.get("hn_comments") or 0)
        score = hn_score / 12.0 + comments / 25.0
        return min(score, 20.0)

    return 0.0


def _freshness_score(published_at: str, now_utc: datetime) -> float:
    published_dt = _parse_iso_datetime(published_at)
    age_hours = max((now_utc - published_dt).total_seconds() / 3600.0, 0.0)

    if age_hours <= 24:
        return 15.0
    if age_hours <= 48:
        return 12.0
    if age_hours <= 72:
        return 10.0
    if age_hours <= 7 * 24:
        return 6.0
    if age_hours <= 30 * 24:
        return 3.0
    return 1.0


def enrich_items(items: list[dict[str, Any]], now_utc: datetime | None = None) -> list[dict[str, Any]]:
    current = now_utc or datetime.now(timezone.utc)
    enriched: list[dict[str, Any]] = []

    for item in items:
        title = normalize_title(str(item.get("title") or ""))
        if not title:
            continue

        url = str(item.get("url") or "").strip()
        canonical = canonicalize_url(url)
        source_id = str(item.get("source_id") or url or title)

        summary = normalize_title(str(item.get("summary") or ""))
        keyword_points, tags = _keyword_score(f"{title}\n{summary}")

        source_weight = SOURCE_WEIGHTS.get(str(item.get("source") or ""), 10.0)
        popularity = _popularity_score(item)
        freshness = _freshness_score(str(item.get("published_at") or ""), current)

        total_score = round(source_weight + keyword_points + popularity + freshness, 2)

        enriched_item = dict(item)
        enriched_item.update(
            {
                "title": title,
                "summary": summary,
                "canonical_url": canonical,
                "title_norm": title.lower(),
                "content_hash": _build_content_hash(source_id, title, canonical or url),
                "score": total_score,
                "tags": tags,
            }
        )
        if not enriched_item.get("published_at"):
            enriched_item["published_at"] = _iso_utc(current)
        enriched.append(enriched_item)

    return enriched


def dedup_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    seen_hashes: set[str] = set()
    unique: list[dict[str, Any]] = []

    for item in items:
        canonical_url = str(item.get("canonical_url") or "")
        title_norm = str(item.get("title_norm") or "")
        content_hash = str(item.get("content_hash") or "")
        domain = _domain_from_url(canonical_url)

        if canonical_url and canonical_url in seen_urls:
            continue
        if title_norm and domain and (domain, title_norm) in seen_titles:
            continue
        if content_hash and content_hash in seen_hashes:
            continue

        if canonical_url:
            seen_urls.add(canonical_url)
        if title_norm and domain:
            seen_titles.add((domain, title_norm))
        if content_hash:
            seen_hashes.add(content_hash)

        unique.append(item)

    return unique


def select_candidates(items: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    return [item for item in items if float(item.get("score") or 0) >= threshold]


def build_topn(items: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    sorted_items = sorted(
        items,
        key=lambda item: (
            -float(item.get("score") or 0),
            _parse_iso_datetime(str(item.get("published_at") or "")).timestamp(),
        ),
    )
    return sorted_items[: max(top_n, 0)]


def _format_top_markdown(run_date: date, top_items: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    lines = [
        f"# AI 资讯 Top {len(top_items)} - {run_date.isoformat()}",
        "",
        f"- 抓取总数: {stats['total_fetched']}",
        f"- 去重后数量: {stats['after_dedup']}",
        f"- 阈值以上数量: {stats['above_threshold']}",
        f"- 分数阈值: {stats['threshold']}",
        "",
    ]

    if not top_items:
        lines.append("该日期暂无满足阈值条件的资讯。")
        return "\n".join(lines)

    for index, item in enumerate(top_items, start=1):
        tags = ", ".join(item.get("tags") or [])
        source_key = str(item.get("source") or "").lower()
        source_label = SOURCE_LABELS.get(source_key, source_key or "-")
        lines.extend(
            [
                f"## {index}. {item.get('title', '')}",
                f"- 来源: {source_label}",
                f"- 分数: {item.get('score')}",
                f"- 发布时间: {item.get('published_at')}",
                f"- 标签: {tags or '-'}",
                f"- 链接: {item.get('url')}",
            ]
        )
        summary = str(item.get("summary") or "").strip()
        if summary:
            if re.search(r"[\u4e00-\u9fff]", summary):
                lines.append(f"- 摘要: {summary}")
            else:
                lines.append("- 摘要: （原文为英文，未做机器翻译）")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_outputs(
    output_root: str,
    run_date: date,
    total_items: list[dict[str, Any]],
    deduped_items: list[dict[str, Any]],
    candidate_items: list[dict[str, Any]],
    top_items: list[dict[str, Any]],
    threshold: float,
    run_meta: dict[str, Any] | None = None,
) -> Path:
    out_dir = Path(output_root) / run_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "total_fetched": len(total_items),
        "after_dedup": len(deduped_items),
        "above_threshold": len(candidate_items),
        "top_n": len(top_items),
        "threshold": threshold,
        "generated_at": _iso_utc(datetime.now(timezone.utc)),
    }

    payload = {
        "run_date": run_date.isoformat(),
        "stats": stats,
        "run_meta": run_meta or {},
        "items": deduped_items,
    }

    raw_json = out_dir / "raw.json"
    raw_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    top_md = out_dir / "top.md"
    top_md.write_text(_format_top_markdown(run_date, top_items, stats), encoding="utf-8")

    return out_dir
