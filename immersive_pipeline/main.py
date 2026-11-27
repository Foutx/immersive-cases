"""Оркестратор пайплайна cases.json.

    python main.py all                  # этапы 1→4
    python main.py stage1 [--seed teamLab]
    python main.py stage2 [--force] [--limit 10]
    python main.py stage3
    python main.py stage4 [--strict] [--publish ../cases.json]
    python main.py stage4 --save-db      # JSON + SQLite
    python main.py import-db --input data/enriched_cases.json
    python main.py status               # сколько кейсов на каждом шаге

Каждый этап читает и пишет JSON-файлы в data/, поэтому его можно
перезапускать: уже собранное не теряется и не запрашивается повторно.
"""
import argparse
import asyncio
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    if args.command == "import-db":
        from services.pipeline_import import import_pipeline_file
        result = import_pipeline_file(args.input, args.db_path)
        log("DONE", "SQLite: " + json.dumps(result, ensure_ascii=False))
        return
    llm = make_llm(args.llm) if args.command in ("stage1", "stage2", "all", "llm-check") else None
    try:
        await run_with_llm(args, llm)
    finally:
        if getattr(llm, "name", None) == "aitunnel":
            log("INFO", f"AI Tunnel: попыток {llm.calls}; по usage API: "
                        f"{llm.tokens_in} токенов входа, {llm.tokens_out} выхода")


async def run_with_llm(args, llm):
    if args.command == "llm-check":
        if getattr(llm, "name", None) != "aitunnel":
            raise ValueError("Для llm-check используйте --llm aitunnel")
        result = await llm.complete_json("Reply with a JSON object.", 'Return exactly {"ok": true}.')
        if result != {"ok": True}:
            raise ValueError("Проверочный запрос вернул неожиданный JSON")
        log("DONE", f"AI Tunnel: {config.AITUNNEL_MODEL}; JSON получен")
        return
    if args.command in ("stage1", "all"):
        seeds = load_json(config.SEEDS_FILE, [])
        await run_stage1(seeds=[s for s in seeds if s.get("enabled", True)], llm=llm, only_seed=args.seed, max_pages=args.limit or config.CRAWL_MAX_PAGES_PER_SEED)
    if args.command in ("stage2", "all"):
        await run_stage2(llm=llm, force=args.force, limit=args.limit)
    if args.command in ("stage3", "all"):
        run_stage3()
    if args.command in ("stage4", "all"):
        run_stage4(strict=args.strict, publish_to=args.publish, save_db=args.save_db, db_path=args.db_path)


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("command", choices=["all", "stage1", "stage2", "stage3", "stage4", "status", "import-db", "llm-check"])
    cli.add_argument("--llm", choices=["aitunnel", "gigachat", "ollama", "openai", "none"], help="переопределить LLM_PROVIDER")
    cli.add_argument("--seed", help="этап 1: обработать только seed с этим именем")
    cli.add_argument("--force", action="store_true", help="этап 2: заново искать видео для всех кейсов")
    cli.add_argument("--limit", type=int, help="этап 2: обработать не больше N кейсов")
    cli.add_argument("--strict", action="store_true", help="этап 4: ошибка, если кейсов не ровно 100")
    cli.add_argument("--publish", type=Path, help="этап 4: скопировать итог, например в ../cases.json")
    cli.add_argument("--save-db", action="store_true", help="stage4/all: also import validated cards into SQLite")
    cli.add_argument("--db-path", type=Path, help="alternative SQLite database file")
    cli.add_argument("--input", type=Path, help="import-db: raw/enriched/scored/top JSON file")
    args = cli.parse_args()
    if args.command == "import-db" and args.input is None:
        cli.error("import-db requires --input")
    if args.input is not None and args.command != "import-db":
        cli.error("--input is only supported with import-db")
    if args.save_db and args.command not in ("stage4", "all"):
        cli.error("--save-db is only supported with stage4/all")
    if args.db_path is not None and args.command != "import-db" and not args.save_db:
        cli.error("--db-path requires import-db or --save-db")
    if args.limit is not None and args.limit < 1:
        cli.error("--limit must be positive")
    if args.command == "status":
        return status()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log("WARN", "остановлено; промежуточные данные сохранены — можно перезапустить")
    except (ValueError, OSError, sqlite3.Error) as exc:
        log("ERROR", str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
