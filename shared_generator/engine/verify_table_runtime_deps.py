#!/usr/bin/env python3
import json
import sys

import pyarrow

EXPECTED = "25.0.1"
if pyarrow.__version__ != EXPECTED:
    raise SystemExit(f"PyArrow {EXPECTED} required; found {pyarrow.__version__}")
print(json.dumps({"status": "PASS", "python": sys.version.split()[0], "pyarrow": pyarrow.__version__}))
