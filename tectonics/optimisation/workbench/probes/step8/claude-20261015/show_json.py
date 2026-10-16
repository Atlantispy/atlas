"""Print a JSON path from a file, compactly.

Usage: python -B show_json.py FILE [key.path.with.dots] [--keys] [--maxlen N]
Integer path parts index lists.
"""
import json
import sys


def main():
    path = sys.argv[1]
    keypath = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else ""
    keys_only = "--keys" in sys.argv
    maxlen = None
    if "--maxlen" in sys.argv:
        maxlen = int(sys.argv[sys.argv.index("--maxlen") + 1])
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if keypath:
        for part in keypath.split("."):
            if isinstance(obj, list):
                obj = obj[int(part)]
            else:
                obj = obj[part]
    if keys_only:
        if isinstance(obj, dict):
            for k, v in obj.items():
                size = len(json.dumps(v))
                print(f"{k}\t{type(v).__name__}\t{size}")
        elif isinstance(obj, list):
            print(f"list of {len(obj)}")
        return
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    if maxlen is not None and len(text) > maxlen:
        text = text[:maxlen] + "\n...[truncated]"
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
