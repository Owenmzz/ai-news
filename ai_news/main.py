"""CLI entry point for AI News V1-Lite."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from ai_news.fetchers import fetch_by_source_spec
    from ai_news.pipeline import build_topn, dedup_items, enrich_items, save_outputs, select_candidates
    from ai_news.source_config import load_source_config, parse_source_ids, select_sources
except ModuleNotFoundError:
    # Support `python ai_news/main.py ...` execution style.
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    from ai_news.fetchers import fetch_by_source_spec
    from ai_news.pipeline import build_topn, dedup_items, enrich_items, save_outputs, select_candidates
    from ai_news.source_config import load_source_config, parse_source_ids, select_sources


def parse_date_args(date_value: str | None, relative: str) -> date:
    if date_value:
        try:
            return datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"invalid --date format: {date_value}, expected YYYY-MM-DD") from exc

    today = datetime.now(timezone.utc).date()
    offsets = {
        "today": 0,
        "yesterday": 1,
        "day-before": 2,
    }
    return today - timedelta(days=offsets[relative])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI News V1-Lite (manual trigger)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one collection task")
    run_parser.add_argument("--date", help="target date in YYYY-MM-DD")
    run_parser.add_argument(
        "--relative",
        default="yesterday",
        choices=["today", "yesterday", "day-before"],
        help="relative date when --date is not provided",
    )
    run_parser.add_argument(
        "--config",
        default="config/sources.json",
        help="source config path",
    )
    run_parser.add_argument(
        "--sources",
        default="",
        help="comma separated source IDs from config, default uses all enabled sources",
    )
    run_parser.add_argument("--top-n", type=int, default=10, help="top item count")
    run_parser.add_argument("--threshold", type=float, default=45.0, help="score threshold")
    run_parser.add_argument("--out", default="docs/output", help="output directory")
    run_parser.add_argument("--dry-run", action="store_true", help="print summary only")

    return parser


def run_task(args: argparse.Namespace) -> int:
    run_date = parse_date_args(args.date, args.relative)

    config = load_source_config(args.config)
    selected_ids = parse_source_ids(args.sources)
    selected_sources = select_sources(config, selected_ids)

    global_config = config.get("global", {})
    try:
        default_timeout = int(global_config.get("request_timeout", 20))
    except (TypeError, ValueError):
        default_timeout = 20
    default_timeout = max(default_timeout, 1)

    raw_items: list[dict] = []
    source_errors: list[str] = []

    source_labels = [source["id"] for source in selected_sources]
    print(f"[run_date] {run_date.isoformat()}")
    print(f"[sources] {', '.join(source_labels)}")

    for source in selected_sources:
        source_id = source["id"]
        source_type = source["type"]
        print(f"[fetch] {source_id} ({source_type}) ...")
        try:
            fetched = fetch_by_source_spec(
                source_spec=source,
                target_date=run_date,
                default_timeout=default_timeout,
            )
            print(f"  fetched: {len(fetched)}")
            raw_items.extend(fetched)
        except Exception as exc:  # noqa: BLE001
            message = f"{source_id} failed: {exc}"
            source_errors.append(message)
            print(f"  warning: {message}")

    enriched = enrich_items(raw_items)
    deduped = dedup_items(enriched)
    candidates = select_candidates(deduped, args.threshold)
    top_items = build_topn(candidates, args.top_n)

    print("[summary]")
    print(f"  total_fetched: {len(raw_items)}")
    print(f"  after_dedup: {len(deduped)}")
    print(f"  above_threshold: {len(candidates)}")
    print(f"  top_n: {len(top_items)}")

    if args.dry_run:
        if top_items:
            print("[preview]")
            for idx, item in enumerate(top_items, start=1):
                print(f"  {idx}. ({item.get('score')}) {item.get('title')} -> {item.get('url')}")
        else:
            print("[preview] no qualified items")
    else:
        output_path = save_outputs(
            output_root=args.out,
            run_date=run_date,
            total_items=raw_items,
            deduped_items=deduped,
            candidate_items=candidates,
            top_items=top_items,
            threshold=args.threshold,
            run_meta={
                "config_path": config.get("config_path"),
                "selected_sources": source_labels,
                "source_count": len(source_labels),
            },
        )
        print(f"[output] {output_path}")

    if source_errors:
        print("[warnings]")
        for message in source_errors:
            print(f"  - {message}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            return run_task(args)
        except ValueError as exc:
            print(f"error: {exc}")
            return 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
