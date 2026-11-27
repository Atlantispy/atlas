"""Private one-shot exact-interface subprocess entry point."""
if __name__ == '__main__':
    import sys
    from atlas_tectonics.integration.parallel.dispatch import worker_main
    worker_main(sys.argv[1])
