"""Atlas remake: isolated mathematical foundations, WORKING NON-CANON.

Vibe-coded with OpenAI ChatGPT/Codex under the owner's direction.
No imports, migration or replacement of historical Atlas implementations.
"""
from ._validation import TectonicsError
from .parameters import FlexureParameters, PeriodicGrid1D, ThermalParameters, identity
from .kinematics import BoundaryMotion, Rotation, boundary_motion, rigid_velocity
from .transport import TransportResult, advect_thickness
from .thermal import half_space_temperature
from .flexure import PeriodicFlexure

__version__ = "0.1.0.dev0"
__all__ = ["TectonicsError", "FlexureParameters", "PeriodicGrid1D", "ThermalParameters",
           "identity", "BoundaryMotion", "Rotation", "boundary_motion", "rigid_velocity",
           "TransportResult", "advect_thickness", "half_space_temperature", "PeriodicFlexure"]
