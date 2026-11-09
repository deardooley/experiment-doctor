"""Operator-only bounded aggregate health snapshot; no prompts, credentials or sessions."""
import argparse
import json
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/var/lib/experiment-doctor'))
    args = parser.parse_args()
    result = {'at': time.time(), 'free_disk_bytes': shutil.disk_usage(args.root).free}
    for name, filename, table in (('experiments', 'control/api.sqlite3', 'experiments'),
                                  ('jobs', 'runner/runner.sqlite3', 'jobs')):
        with closing(sqlite3.connect(f'file:{args.root / filename}?mode=ro', uri=True)) as db:
            result[name] = dict(db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status'))
            if table == 'jobs':
                result['job_reasons'] = dict(db.execute('SELECT coalesce(reason,"pending"),count(*) FROM jobs GROUP BY reason'))
                result['cleanup'] = dict(db.execute('SELECT cleanup,count(*) FROM jobs GROUP BY cleanup'))
            else:
                result['worker_health'] = dict(db.execute('SELECT key,value FROM health'))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
