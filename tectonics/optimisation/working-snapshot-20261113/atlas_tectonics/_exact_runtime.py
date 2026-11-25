"""Bind the selected rational backend at the first tectonics request."""
from ._validation import TectonicsError
from .integration_worker_bootstrap import bind_shared_exact

bind_shared_exact()
from atlas_shared.exact.exact_arithmetic import select

selected = select(TectonicsError)
# Bind the executing route into the code identity independently of its provenance.
BACKEND = selected.backend
