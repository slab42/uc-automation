#!/usr/bin/env python3
# TITLE: Log Search

"""
Search all log files under _logs for a text string and print every matching line.

Prompts for the search text (case-insensitive), reads every file under the repo-root
_logs folder (including subfolders and rotated logs), and prints each matching line
prefixed with its file name and line number. After the output, offers to export the
results to a .log file in the _DATA folder, then offers another search.

No logger is created on purpose: the script reads _logs, so writing its own log there
would add noise to future searches.

Export: _DATA/<timestamp>-log_search.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from setup.prompt_utils import prompt_yes_no

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / '_logs'
DATA_DIR = ROOT / '_DATA'


def find_log_files(log_dir):
    """Return all regular files under log_dir, sorted by path."""
    return sorted(p for p in log_dir.rglob('*') if p.is_file())


def search_file(path, needle):
    """Return list of (line_number, line) in path containing needle (case-insensitive)."""
    matches = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for number, line in enumerate(f, 1):
            if needle in line.lower():
                matches.append((number, line.rstrip('\r\n')))
    return matches


def run_search():
    """Prompt for text, print matches, and offer export."""
    text = input('Text to search for: ').strip()
    if not text:
        print('No search text entered.')
        return

    files = find_log_files(LOG_DIR)
    needle = text.lower()
    results = []
    for path in files:
        try:
            matches = search_file(path, needle)
        except OSError as e:
            print(f'Unable to read {path.name}: {e}')
            continue
        rel = path.relative_to(LOG_DIR).as_posix()
        results.extend(f'{rel}:{number}: {line}' for number, line in matches)

    print()
    for row in results:
        print(row)
    print(f'\n{len(results)} matching line(s) for "{text}" across {len(files)} file(s) in _logs')

    if results and prompt_yes_no('Export results to a .log file in _DATA?', default=False):
        DATA_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        out_path = DATA_DIR / f'{timestamp}-log_search.log'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(f'Search text: {text}\n')
            f.write('\n'.join(results) + '\n')
        print(f'Exported to {out_path}')


def main():
    if not LOG_DIR.is_dir():
        print(f'Log folder not found: {LOG_DIR}')
        return

    while True:
        run_search()
        if not prompt_yes_no('Search again?', default=False):
            break


if __name__ == '__main__':
    main()
