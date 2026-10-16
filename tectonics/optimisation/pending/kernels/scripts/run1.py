"""Run one command with a wall-clock limit, as a child runq can see (a GNU timeout replacement).

Usage: python -B -I run1.py SECONDS COMMAND [ARGS...]
Exit: the command's exit code; 124 if it ran past SECONDS (it is then terminated), as GNU timeout.
Why (16 Oct, ck/d5/tree_probe.py): under Git Bash, `timeout N cmd &` leaves cmd outside the Windows
parent chain, so runq's tree sampler (psutil children(recursive=True)) never sees it (0.01 GiB seen for a
0.22 GiB child, three runs); `python run1.py N cmd &` keeps both processes in the chain.
stdin/stdout/stderr are inherited (the caller redirects them).
"""
import subprocess
import sys


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    seconds = float(argv[0])
    proc = subprocess.Popen(argv[1:])
    try:
        code = proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print('run1: %s ran past %g s; terminated' % (argv[1], seconds), file=sys.stderr, flush=True)
        return 124
    if not 0 <= code <= 255:
        print('run1: %s exit code %d' % (argv[1], code), file=sys.stderr, flush=True)
        return 1
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
