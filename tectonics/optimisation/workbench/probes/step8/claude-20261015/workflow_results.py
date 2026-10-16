"""Extract workflow agent results from a journal.jsonl into one JSON file.

Usage: python -B workflow_results.py WORKFLOW_DIR OUT.json [--summary]
"""
import json
import os
import sys


def main():
    directory, out = sys.argv[1], sys.argv[2]
    labels = {}
    for name in os.listdir(directory):
        if name.endswith('.meta.json'):
            with open(os.path.join(directory, name), encoding='utf-8') as f:
                labels[name[len('agent-'):-len('.meta.json')]] = json.load(f).get('description')
    results = {}
    with open(os.path.join(directory, 'journal.jsonl'), encoding='utf-8') as f:
        for line in f:
            row = json.loads(line)
            if row.get('type') == 'result':
                label = labels.get(row.get('agentId'), row.get('agentId'))
                results[label] = row.get('result')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    sys.stdout.reconfigure(encoding='utf-8')
    if '--summary' in sys.argv:
        for label, result in results.items():
            if isinstance(result, dict) and 'rows' in result:
                for r in result['rows']:
                    print(f"[{label}] {r['id']}: {r['status']} :: {r['remaining_work'][:300]}")
            else:
                print(f"[{label}] {str(result)[:200]}")


if __name__ == '__main__':
    main()
