"""Use immutable release metadata on deployed hosts; Git only for source checkouts."""
import json
import re
import subprocess


def revision(root):
    manifest = root / 'release.json'
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        if not re.fullmatch(r'[a-f0-9]{40}', data['git_sha']) or not isinstance(data['working_tree_dirty'], bool):
            raise ValueError('Invalid installed release provenance')
        return data['git_sha'], data['working_tree_dirty']
    try:
        git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True)
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True)
        return git.stdout.strip() or 'unavailable', bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    except FileNotFoundError:
        return 'unavailable', None
