"""
Legible Studios - Constraint validators for the permit pipeline.

Code and Cost are post-solve validators: they take generated geometry and
return violations + metrics. Climate/Structural/Acoustic studios were archived
on 2026-04-25 as out of scope for the permit-set product.
"""

from .core.constraint_lens import ConstraintLens, LensResult
from .studios.code_studio import CodeStudio
from .studios.cost_studio import CostStudio

__all__ = [
    "ConstraintLens",
    "LensResult",
    "CodeStudio",
    "CostStudio",
]
