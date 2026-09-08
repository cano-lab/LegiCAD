"""
Core studio management - maps LOD pattern to constraint domains.

The StudioManager is the equivalent of LODManager, but for constraint lenses
instead of zoom levels. It handles:
- Studio level transitions
- Cross-studio blending
- Constraint intensity calculations
"""

from enum import IntEnum
from typing import Dict, Tuple, Optional, Callable
from dataclasses import dataclass
import math


class StudioLevel(IntEnum):
    """Studio levels - constraint domains from coarse to fine."""
    CLIMATE = 1      # Environmental topology - thermal, wind, solar
    STRUCTURAL = 2   # Forces and members - loads, spans, materials
    CODE = 3         # Compliance fixtures - egress, accessibility, zoning
    COST = 4         # Specification view - budget, constructability
    ACOUSTIC = 5     # Detail documentation - sound, isolation


@dataclass
class StudioInfo:
    """Metadata for each studio."""
    name: str
    description: str
    color: Tuple[int, int, int]  # RGB
    icon: str
    content_types: set


# Studio metadata
STUDIO_INFO = {
    StudioLevel.CLIMATE: StudioInfo(
        name="Climate",
        description="Environmental topology - thermal, wind, solar",
        color=(100, 149, 237),  # Cornflower blue
        icon="🌡️",
        content_types={
            "solar-zones",
            "wind-roses",
            "thermal-gradients",
            "daylight-zones",
            "shading-analysis",
        },
    ),
    StudioLevel.STRUCTURAL: StudioInfo(
        name="Structural",
        description="Forces and members - loads, spans, materials",
        color=(144, 238, 144),  # Light green
        icon="🏗️",
        content_types={
            "load-paths",
            "moment-diagrams",
            "deflection-shapes",
            "member-sizes",
            "connection-points",
        },
    ),
    StudioLevel.CODE: StudioInfo(
        name="Code",
        description="Compliance fixtures - egress, accessibility, zoning",
        color=(255, 215, 0),  # Gold
        icon="📋",
        content_types={
            "egress-routes",
            "accessibility-zones",
            "height-limits",
            "setback-lines",
            "occupancy-loads",
        },
    ),
    StudioLevel.COST: StudioInfo(
        name="Cost",
        description="Specification view - budget, constructability",
        color=(255, 165, 0),  # Orange
        icon="💰",
        content_types={
            "cost-zones",
            "material-takeoffs",
            "constructability-notes",
            "labor-estimates",
        },
    ),
    StudioLevel.ACOUSTIC: StudioInfo(
        name="Acoustic",
        description="Detail documentation - sound, isolation",
        color=(255, 99, 71),  # Tomato
        icon="🔊",
        content_types={
            "sound-contours",
            "isolation-zones",
            "rt60-values",
            "noise-ratings",
        },
    ),
}


class StudioManager:
    """
    Manages studio level transitions and constraint lens activation.
    
    Like LODManager, but for constraint domains. Controls which studio's
    interpretation is active and handles smooth transitions between them.
    """

    # Fade ranges for studio transitions [start_fade, full_visible]
    STUDIO_FADE_RANGES = {
        StudioLevel.CLIMATE: (0.0, 0.2),
        StudioLevel.STRUCTURAL: (0.15, 0.35),
        StudioLevel.CODE: (0.30, 0.50),
        StudioLevel.COST: (0.45, 0.65),
        StudioLevel.ACOUSTIC: (0.60, 0.80),
    }

    TRANSITION_DURATION = 0.15  # seconds

    def __init__(self):
        self._current_level = StudioLevel.CLIMATE
        self._transition_progress = 0.0
        self._constraint_intensity = 0.5  # 0-1, how strict constraints are
        self._studio_override: Optional[StudioLevel] = None
        self._listeners: list[Callable] = []

    @property
    def current_level(self) -> StudioLevel:
        """Get current active studio level."""
        return self._studio_override or self._current_level

    @property
    def constraint_intensity(self) -> float:
        """Get current constraint intensity (0-1)."""
        return self._constraint_intensity

    @constraint_intensity.setter
    def constraint_intensity(self, value: float):
        """Set constraint intensity (0-1)."""
        self._constraint_intensity = max(0.0, min(1.0, value))

    def set_studio_override(self, level: Optional[StudioLevel]):
        """Manually override studio level (None for auto)."""
        self._studio_override = level
        self._notify_change()

    def calculate_opacity(self, level: StudioLevel, focus: float) -> float:
        """
        Calculate opacity for a studio level at given focus.
        
        Args:
            level: Studio level
            focus: Focus value 0-1 (like zoom for LOD)
            
        Returns:
            Opacity 0.0-1.0
        """
        if self._studio_override is not None:
            return 1.0 if level == self._studio_override else 0.0

        if level not in self.STUDIO_FADE_RANGES:
            return 1.0

        start, end = self.STUDIO_FADE_RANGES[level]

        if focus <= start:
            return 0.0
        elif focus >= end:
            return 1.0
        else:
            # Smooth ease-out cubic
            t = (focus - start) / (end - start)
            return 1.0 - pow(1.0 - t, 3)

    def calculate_all_opacities(self, focus: float) -> Dict[StudioLevel, float]:
        """Calculate opacities for all studio levels."""
        return {
            level: self.calculate_opacity(level, focus)
            for level in StudioLevel
        }

    def get_dominant_studio(self, focus: float) -> StudioLevel:
        """Get the dominant studio at given focus."""
        if self._studio_override is not None:
            return self._studio_override

        opacities = self.calculate_all_opacities(focus)

        # Find highest level with >50% opacity
        for level in reversed(list(StudioLevel)):
            if opacities[level] > 0.5:
                return level
        return StudioLevel.CLIMATE

    def get_studio_info(self, level: StudioLevel) -> StudioInfo:
        """Get metadata for a studio level."""
        return STUDIO_INFO[level]

    def get_content_types(self, level: StudioLevel) -> set:
        """Get content types that emerge at this studio level."""
        return STUDIO_INFO[level].content_types

    def add_listener(self, callback: Callable):
        """Add listener for studio changes."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """Remove listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_change(self):
        """Notify all listeners of change."""
        for listener in self._listeners:
            listener(self._current_level, self._transition_progress)

    def transition_to(self, target_level: StudioLevel, duration: float = 0.3):
        """Animate transition to target studio level."""
        # This would integrate with animation system
        self._current_level = target_level
        self._notify_change()

    def get_css_rules(self, focus: float) -> str:
        """Generate CSS rules for studio visibility."""
        opacities = self.calculate_all_opacities(focus)
        rules = []

        rules.append(f'[data-studio] {{ transition: opacity {self.TRANSITION_DURATION}s ease-out; }}')

        for level, opacity in opacities.items():
            studio_class = f"studio-{level.value}"
            opacity_val = round(opacity, 2)

            if opacity_val <= 0:
                rules.append(f'.{studio_class} {{ opacity: 0; pointer-events: none; }}')
            elif opacity_val >= 1:
                rules.append(f'.{studio_class} {{ opacity: 1; }}')
            else:
                rules.append(f'.{studio_class} {{ opacity: {opacity_val}; }}')

        return '\n'.join(rules)
