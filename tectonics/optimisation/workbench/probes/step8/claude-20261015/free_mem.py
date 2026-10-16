"""Print available physical memory and free disk on the volume holding R (read-only)."""
import shutil
from pathlib import Path

import psutil

R = Path(__file__).resolve().parents[3]


def main():
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage(R)
    print(f'available {vm.available/2**30:.1f} GiB of {vm.total/2**30:.1f} GiB; '
          f'disk free {disk.free/2**30:.0f} GiB of {disk.total/2**30:.0f} GiB')


if __name__ == '__main__':
    main()
