"""Review-only, source-pinned spatial successors; not a production installation."""

from .grid import (Grid, SpatialError, RemapResult, categorical, cell_fractions,
                   extensive, intensive, sample_cells)
from .adapters import (prepare_b1a3_fields, prepare_c1r7_fields,
                       sample_political_evidence, require_native_contacts,
                       verify_sources)

