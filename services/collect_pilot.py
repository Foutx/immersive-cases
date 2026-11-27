"""Run a bounded paid pilot against the international source list, creating drafts only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--max-calls',type=int,choices=range(2,21),default=13,
                     help='Maximum paid requests including one connectivity check')
    args=cli.parse_args()
    data=ROOT/'data'/'pilot'
    db=ROOT/'data'/'pilot-preview.sqlite3'
    env=dict(os.environ,DATA_DIR=str(data),SEEDS_FILE=str(ROOT/'immersive_pipeline'/'seeds.international.json'),
             AITUNNEL_MAX_CALLS=str(args.max_calls-1))
    def run(*args):
        return subprocess.run([sys.executable,'immersive_pipeline/main.py',*args],cwd=ROOT,env=env).returncode
    ready=run('llm-check','--llm','aitunnel')
    if ready:
        return ready
    result=run('stage1','--llm','aitunnel','--limit','1')
    candidates=data/'raw_candidates.json'
    if candidates.is_file() and json.loads(candidates.read_text(encoding='utf-8-sig')):
        imported=run('import-db','--input',str(candidates),'--db',str(db))
        if imported:
            return imported
        print('Черновики: python -m api.app --db data/pilot-preview.sqlite3 --include-drafts --port 5003')
    else:
        print('Карточек нет. Проверьте ошибки загрузки источников и правила извлечения.',file=sys.stderr)
        return result or 1
    return result

if __name__ == '__main__':
    sys.exit(main())
