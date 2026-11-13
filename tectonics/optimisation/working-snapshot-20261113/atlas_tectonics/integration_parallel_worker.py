"""Private one-shot exact-interface subprocess entry point."""
if __name__ == '__main__':
    import sys
    from .integration_parallel_dispatch import worker_main
    if len(sys.argv) != 2:
        raise SystemExit('one parent-owned job directory required')
    worker_main(sys.argv[1])
