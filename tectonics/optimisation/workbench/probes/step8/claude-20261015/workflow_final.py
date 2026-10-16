"""Save the scouting workflow's final return value and print its verdict table.

Usage: python -B workflow_final.py TASK_OUTPUT_FILE OUT_DIR
Writes inventory-audit.json (verified rows), critic.md, harness.md, builder.md,
exchange-facts.md and baseline-tests.md into OUT_DIR.
"""
import json
import os
import sys


def main():
    source, out = sys.argv[1], sys.argv[2]
    with open(source, encoding='utf-8') as f:
        text = f.read()
    start = text.index('{')
    result, _ = json.JSONDecoder().raw_decode(text[start:])
    if 'result' in result and 'inventory' not in result:
        result = result['result']
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'inventory-audit.json'), 'w', encoding='utf-8') as f:
        json.dump(result['inventory'], f, indent=1, ensure_ascii=False)
    for key, name in (('critic', 'critic.md'), ('harness', 'harness.md'), ('builder', 'builder.md'),
                      ('exchangeFacts', 'exchange-facts.md'), ('tests', 'baseline-tests.md')):
        with open(os.path.join(out, name), 'w', encoding='utf-8') as f:
            f.write(result.get(key) or '')
    sys.stdout.reconfigure(encoding='utf-8')
    for row in result['inventory']:
        verdict = '' if row['verified'] is None else ('confirmed' if row['verified'] else 'REFUTED')
        print(f"{row['id']:<42} {row['status']:<13} -> {row['final_status']:<13} {verdict}")
        if row['verified'] is False:
            print('    reason:', row['verifier_reason'][:600])


if __name__ == '__main__':
    main()
