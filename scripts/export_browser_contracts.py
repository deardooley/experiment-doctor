"""Export pure schema only; no API state, credentials or runtime data is read."""
import argparse
import json
from pathlib import Path

from packages.contracts.presentation import BrowserContracts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / 'apps/web/src/generated/contracts.schema.json'
    schema = json.dumps(BrowserContracts.model_json_schema(), indent=2, sort_keys=True) + '\n'
    if args.check:
        if path.read_text() != schema:
            raise SystemExit('Browser schema drift: run python -m scripts.export_browser_contracts')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(schema)


if __name__ == '__main__':
    main()
