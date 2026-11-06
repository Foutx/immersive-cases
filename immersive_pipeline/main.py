"""Оркестратор пайплайна cases.json.

    python main.py all                  # этапы 1→4
    python main.py stage1 [--seed teamLab]
    python main.py stage2 [--force] [--limit 10]
    python main.py stage3
    python main.py stage4 [--strict] [--publish ../cases.json]
    python main.py status               # сколько кейсов на каждом шаге

Каждый этап читает и пишет JSON-файлы в data/, поэтому его можно
перезапускать: уже собранное не теряется и не запрашивается повторно.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from stages.common import load_json, log  # noqa: E402
from stages.llm import make_llm  # noqa: E402
from stages.stage1_discovery import run_stage1  # noqa: E402
from stages.stage2_enrichment import run_stage2  # noqa: E402
from stages.stage3_scoring import run_stage3  # noqa: E402
from stages.stage4_exporter import run_stage4  # noqa: E402


def status():
    for name, path in [("ручные кандидаты", config.MANUAL_CANDIDATES), ("этап 1", config.RAW_CANDIDATES),
                       ("этап 2", config.ENRICHED_CASES), ("этап 3 (оценено)", config.SCORED_CASES),
                       ("этап 3 (топ)", config.TOP_CASES), ("этап 4", config.FINAL_CASES)]:
        rows = load_json(path, None)
        extra = ""
        if rows and name == "этап 2":
            extra = f", с видео: {sum(any(v.get('verified') for v in r.get('videos', [])) for r in rows)}"
        log("INFO", f"{name:18} {'—' if rows is None else len(rows):>4}{extra}  {path}")


async def run(args):
    llm = make_llm(args.llm) if args.command in ("stage1", "stage2", "all") else None
    if args.command in ("stage1", "all"):
        seeds = load_json(config.SEEDS_FILE, [])
        await run_stage1(seeds=[s for s in seeds if s.get("enabled", True)], llm=llm, only_seed=args.seed, max_pages=args.limit or config.CRAWL_MAX_PAGES_PER_SEED)
    if args.command in ("stage2", "all"):
        await run_stage2(llm=llm, force=args.force, limit=args.limit)
    if args.command in ("stage3", "all"):
        run_stage3()
    if args.command in ("stage4", "all"):
        run_stage4(strict=args.strict, publish_to=args.publish)


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("command", choices=["all", "stage1", "stage2", "stage3", "stage4", "status"])
    cli.add_argument("--llm", choices=["gigachat", "ollama", "openai", "none"], help="переопределить LLM_PROVIDER")
    cli.add_argument("--seed", help="этап 1: обработать только seed с этим именем")
    cli.add_argument("--force", action="store_true", help="этап 2: заново искать видео для всех кейсов")
    cli.add_argument("--limit", type=int, help="этап 2: обработать не больше N кейсов")
    cli.add_argument("--strict", action="store_true", help="этап 4: ошибка, если кейсов не ровно 100")
    cli.add_argument("--publish", type=Path, help="этап 4: скопировать итог, например в ../cases.json")
    args = cli.parse_args()
    if args.command == "status":
        return status()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log("WARN", "остановлено; промежуточные данные сохранены — можно перезапустить")
    except ValueError as exc:
        log("ERROR", str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
