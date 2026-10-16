"""Mutants shared by harness_sanity*.py."""
MUTANTS = {
    'store-before-overflow-check': (
        "            if total > sys.maxsize:\n"
        "                raise OverflowError('Exact scalar envelope exceeds addressable storage')\n"
        "            self._envelope = ((peak, slots, containers, total)\n"
        "                              if type(peak) is int and type(slots) is int and type(containers) is int else None)\n",
        "            self._envelope = ((peak, slots, containers, total)\n"
        "                              if type(peak) is int and type(slots) is int and type(containers) is int else None)\n"
        "            if total > sys.maxsize:\n"
        "                raise OverflowError('Exact scalar envelope exceeds addressable storage')\n"),
    'ignore-containers-identity': (
        "                and envelope[2] is containers):", "                and True):"),
    'add-without-carry': (
        "width = max(max(p+t, s+r)+1, r+t)", "width = max(max(p+t, s+r), r+t)"),
    'skip-lease-check-on-hit': (
        "            total = envelope[3]\n",
        "            total = envelope[3]\n            self.peak_bits = peak\n            return\n"),
}
