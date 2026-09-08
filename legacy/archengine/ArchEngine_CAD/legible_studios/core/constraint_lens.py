"""
Base constraint lens - abstract class for all studios.

Each studio interprets the same building geometry through its constraint domain.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum


class ConstraintPriority(Enum):
    """Priority levels for constraint violations."""
    INFO = "info"           # Good to know, not critical
    WARNING = "warning"     # Should address, doesn't block
    CRITICAL = "critical"   # Must fix, blocks progress


@dataclass
class ConstraintViolation:
    """A single constraint violation or observation."""
    message: str
    priority: ConstraintPriority
    location: Optional[Tuple[float, float]] = None  # x, y in model space
    element_id: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class LensResult:
    """Result of applying a constraint lens to geometry."""
    studio_name: str
    violations: List[ConstraintViolation] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    visual_overlays: List[Dict] = field(default_factory=list)
    score: float = 1.0  # 0-1, overall compliance score

    def add_violation(self, message: str, priority: ConstraintPriority,
                      location: Optional[Tuple[float, float]] = None,
                      element_id: Optional[str] = None,
                      suggestion: Optional[str] = None):
        """Add a constraint violation."""
        self.violations.append(ConstraintViolation(
            message=message,
            priority=priority,
            location=location,
            element_id=element_id,
            suggestion=suggestion
        ))

    def get_critical_count(self) -> int:
        """Count critical violations."""
        return sum(1 for v in self.violations if v.priority == ConstraintPriority.CRITICAL)

    def get_warning_count(self) -> int:
        """Count warnings."""
        return sum(1 for v in self.violations if v.priority == ConstraintPriority.WARNING)


class ConstraintLens(ABC):
    """
    Abstract base class for all constraint lenses (studios).
    
    Each studio implements this to interpret building geometry through
    its specific constraint domain.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Studio name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Studio description."""
        pass

    @abstractmethod
    def analyze(self, geometry: Dict[str, Any], 
                intensity: float = 0.5) -> LensResult:
        """
        Analyze geometry through this constraint lens.
        
        Args:
            geometry: Building geometry data (rooms, walls, openings, etc.)
            intensity: Constraint strictness 0-1
            
        Returns:
            LensResult with violations, metrics, overlays
        """
        pass

    @abstractmethod
    def get_visual_overlays(self, geometry: Dict[str, Any],
                           intensity: float = 0.5) -> List[Dict]:
        """
        Get visual overlays for this studio's interpretation.
        
        Returns list of overlay objects with type, geometry, style.
        """
        pass

    def validate(self, geometry: Dict[str, Any]) -> bool:
        """
        Quick validation - True if no critical violations.
        Override for faster checks when full analysis isn't needed.
        """
        result = self.analyze(geometry, intensity=1.0)
        return result.get_critical_count() == 0

    @staticmethod
    def _normalize_rooms(rooms):
        if isinstance(rooms, dict):
            out = []
            for room_id, data in rooms.items():
                if isinstance(data, dict):
                    out.append({**data, "id": data.get("id", room_id)})
                else:
                    out.append({"id": room_id, "name": room_id})
            return out
        return rooms or []

    @staticmethod
    def _normalize_openings(geometry):
        openings = geometry.get("openings")
        if openings:
            return openings
        merged = []
        for d in geometry.get("doors", []) or []:
            merged.append({**d, "type": d.get("type", "door")})
        for w in geometry.get("windows", []) or []:
            merged.append({**w, "type": w.get("type", "window")})
        return merged

    @staticmethod
    def _normalize_walls(geometry):
        return geometry.get("walls") or geometry.get("walls_batch") or []

    @staticmethod
    def _normalize_floors(geometry):
        return geometry.get("floors") or geometry.get("floors_batch") or []
