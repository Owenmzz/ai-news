"""Source configuration loader and selectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEGACY_SOURCE_TYPE_ALIASES = {
    "rss": "rss",
    "github": "github_trending",
    "hn": "hackernews",
}


def parse_source_ids(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []

    selected: list[str] = []
    for token in raw_value.split(","):
        source_id = token.strip()
        if source_id and source_id not in selected:
            selected.append(source_id)
    return selected


def _normalize_source(raw_source: dict[str, Any], index: int) -> dict[str, Any]:
    source_id = str(raw_source.get("id") or "").strip()
    source_type = str(raw_source.get("type") or "").strip().lower()
    enabled = bool(raw_source.get("enabled", True))
    params = raw_source.get("params") or {}

    if not source_id:
        raise ValueError(f"source[{index}] missing required field: id")
    if not source_type:
        raise ValueError(f"source[{index}] missing required field: type")
    if not isinstance(params, dict):
        raise ValueError(f"source[{index}] field params must be an object")

    return {
        "id": source_id,
        "type": source_type,
        "enabled": enabled,
        "params": params,
    }


def load_source_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise ValueError(f"config file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")

    global_config = data.get("global") or {}
    if not isinstance(global_config, dict):
        raise ValueError("global config must be a JSON object")

    raw_sources = data.get("sources") or []
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be a JSON array")

    normalized_sources: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            raise ValueError(f"source[{index}] must be a JSON object")
        normalized = _normalize_source(raw_source, index)
        source_id = normalized["id"]
        if source_id in seen_ids:
            raise ValueError(f"duplicate source id: {source_id}")
        seen_ids.add(source_id)
        normalized_sources.append(normalized)

    if not normalized_sources:
        raise ValueError("no sources configured")

    return {
        "config_path": str(path.resolve()),
        "global": global_config,
        "sources": normalized_sources,
    }


def get_enabled_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in config["sources"] if source.get("enabled", True)]


def select_sources(config: dict[str, Any], requested_ids: list[str]) -> list[dict[str, Any]]:
    enabled_sources = get_enabled_sources(config)
    if not requested_ids:
        return enabled_sources

    by_id = {source["id"]: source for source in enabled_sources}
    by_type: dict[str, list[dict[str, Any]]] = {}
    for source in enabled_sources:
        source_type = str(source.get("type") or "").strip().lower()
        if not source_type:
            continue
        by_type.setdefault(source_type, []).append(source)

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source_id in requested_ids:
        direct = by_id.get(source_id)
        if direct:
            if direct["id"] not in seen_ids:
                selected.append(direct)
                seen_ids.add(direct["id"])
            continue

        alias_target_type = LEGACY_SOURCE_TYPE_ALIASES.get(source_id.strip().lower())
        if alias_target_type:
            matched = by_type.get(alias_target_type, [])
            if not matched:
                raise ValueError(f"source type has no enabled entries: {source_id}")
            for source in matched:
                if source["id"] in seen_ids:
                    continue
                selected.append(source)
                seen_ids.add(source["id"])
            continue

        available_ids = ", ".join(sorted(by_id.keys()))
        raise ValueError(
            f"source id not found or disabled: {source_id}. available ids: {available_ids}"
        )

    return selected
