"""Validate a batch: python -m contracts.validate path.json"""
import argparse
from pathlib import Path
from .events import ImportBatch

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path)
    args=parser.parse_args()
    try:
        batch=ImportBatch.model_validate_json(args.file.read_bytes())
    except (OSError,ValueError) as exc:
        parser.exit(1,f'Invalid import: {exc}\n')
    print(f'Valid contract {batch.schema_version}: {len(batch.events)} events')

if __name__=='__main__': main()
