"""
LOD Manager - Controls level-of-detail visibility based on zoom level.

Implements continuous LOD transitions where elements fade in smoothly
as you zoom, like focus pulling on a camera. No jarring switches.

Philosophy (from ARCHITECTURE.md):
- LOD isn't about hiding information — it's about presenting what's
  meaningful at your current level of focus
- Transitions are smooth, elements fade in and resolve as you zoom
- The experience should feel magical — you move through the design
  and it reveals itself
"""
from typing import Tuple, Dict
import re
import math


class LODManager:
    """
    Manages continuous level-of-detail visibility based on zoom level.

    LOD Levels (with smooth transitions between):
        0: Structure - walls, basic geometry (always visible)
        1: Enclosure - doors, windows, room names (fades in 3-8% zoom)
        2: Systems - dimensions, fixtures, patterns (fades in 15-30% zoom)
        3: Annotations - notes, callouts, details (fades in 80-120% zoom)

    Resolution order follows architecture: Structure → Enclosure → Systems → Annotations
    """

    # Zoom ranges for each LOD level [start_fade, full_visible]
    # Elements fade from 0 to 1 opacity across this range
    LOD_FADE_RANGES = {
        1: (0.03, 0.08),   # LOD 1: fades in from 3% to 8% zoom
        2: (0.15, 0.30),   # LOD 2: fades in from 15% to 30% zoom
        3: (0.80, 1.20),   # LOD 3: fades in from 80% to 120% zoom
    }

    # Human-readable LOD names
    LOD_NAMES = {
        0: "Structure",
        1: "Enclosure",
        2: "Systems",
        3: "Annotations"
    }

    # Transition duration for CSS animations (seconds)
    TRANSITION_DURATION = 0.15

    def __init__(self):
        self._last_zoom = 1.0
        self._lod_override: int | None = None

    @property
    def lod_override(self) -> int | None:
        """Get manual LOD override, or None for auto."""
        return self._lod_override

    @lod_override.setter
    def lod_override(self, value: int | None):
        """Set manual LOD override (0-3), or None for auto."""
        if value is not None:
            value = max(0, min(3, value))
        self._lod_override = value

    def calculate_opacity(self, zoom: float, lod_level: int) -> float:
        """
        Calculate opacity for a specific LOD level at given zoom.

        Uses smooth easing function for natural fade transitions.

        Args:
            zoom: Current zoom level (1.0 = 100%)
            lod_level: LOD level (0-3)

        Returns:
            Opacity value 0.0 to 1.0
        """
        # LOD 0 is always fully visible
        if lod_level == 0:
            return 1.0

        # Check for manual override
        if self._lod_override is not None:
            return 1.0 if lod_level <= self._lod_override else 0.0

        # Get fade range for this LOD level
        if lod_level not in self.LOD_FADE_RANGES:
            return 1.0

        start_zoom, end_zoom = self.LOD_FADE_RANGES[lod_level]

        if zoom <= start_zoom:
            return 0.0
        elif zoom >= end_zoom:
            return 1.0
        else:
            # Smooth interpolation using ease-out cubic
            t = (zoom - start_zoom) / (end_zoom - start_zoom)
            # Ease-out cubic: 1 - (1-t)^3
            return 1.0 - pow(1.0 - t, 3)

    def calculate_all_opacities(self, zoom: float) -> Dict[int, float]:
        """
        Calculate opacity values for all LOD levels.

        Args:
            zoom: Current zoom level

        Returns:
            Dict mapping LOD level to opacity (0.0-1.0)
        """
        return {
            0: 1.0,  # Always visible
            1: self.calculate_opacity(zoom, 1),
            2: self.calculate_opacity(zoom, 2),
            3: self.calculate_opacity(zoom, 3),
        }

    def get_dominant_lod(self, zoom: float) -> int:
        """
        Get the highest LOD level that is mostly visible (>50% opacity).

        Used for status display.
        """
        if self._lod_override is not None:
            return self._lod_override

        opacities = self.calculate_all_opacities(zoom)

        # Find highest LOD with >50% opacity
        for lod in [3, 2, 1, 0]:
            if opacities[lod] > 0.5:
                return lod
        return 0

    def get_lod_name(self, lod: int) -> str:
        """Get human-readable name for LOD level."""
        return self.LOD_NAMES.get(lod, f"LOD {lod}")

    def get_status_text(self, zoom: float) -> str:
        """
        Get status text showing current LOD state.

        Shows the dominant LOD level and indicates if transitioning.
        """
        dominant = self.get_dominant_lod(zoom)
        opacities = self.calculate_all_opacities(zoom)

        # Check if we're in a transition (any opacity between 0.1 and 0.9)
        transitioning = any(0.1 < op < 0.9 for op in opacities.values())

        name = self.get_lod_name(dominant)
        if transitioning:
            return f"{name}..."  # Ellipsis indicates transition
        return name

    def get_css_rules(self, zoom: float) -> str:
        """
        Generate CSS rules with continuous opacity values.

        Args:
            zoom: Current zoom level

        Returns:
            CSS rules string to inject into SVG
        """
        opacities = self.calculate_all_opacities(zoom)

        rules = []

        # Add transition property for smooth changes
        rules.append(f'[data-lod] {{ transition: opacity {self.TRANSITION_DURATION}s ease-out; }}')

        # Add opacity rules for each LOD level
        for lod, opacity in opacities.items():
            if lod == 0:
                continue  # LOD 0 doesn't need a rule (always visible)

            # Round opacity to 2 decimal places
            opacity = round(opacity, 2)

            if opacity <= 0:
                rules.append(f'[data-lod="{lod}"] {{ opacity: 0; pointer-events: none; }}')
            elif opacity >= 1:
                # Fully visible - no rule needed, but add for consistency
                rules.append(f'[data-lod="{lod}"] {{ opacity: 1; }}')
            else:
                # Partial opacity during fade
                rules.append(f'[data-lod="{lod}"] {{ opacity: {opacity}; }}')

        return '\n'.join(rules)

    def inject_lod_css(self, svg_content: str, zoom: float) -> str:
        """
        Inject LOD visibility CSS into SVG content.

        Args:
            svg_content: Original SVG string
            zoom: Current zoom level

        Returns:
            Modified SVG with LOD CSS injected
        """
        css_rules = self.get_css_rules(zoom)

        # Find the closing </style> tag and inject before it
        style_close_pattern = r'(</style>)'
        if re.search(style_close_pattern, svg_content):
            # Inject into existing style block
            injection = f'\n/* LOD visibility (zoom: {zoom:.2f}) */\n{css_rules}\n'
            svg_content = re.sub(style_close_pattern, injection + r'\1', svg_content, count=1)
        else:
            # No existing style, add one after <defs> or at start of SVG
            defs_pattern = r'(<defs[^>]*>)'
            if re.search(defs_pattern, svg_content):
                injection = f'\n<style>\n/* LOD visibility (zoom: {zoom:.2f}) */\n{css_rules}\n</style>'
                svg_content = re.sub(defs_pattern, r'\1' + injection, svg_content, count=1)
            else:
                # Add defs with style after opening svg tag
                svg_pattern = r'(<svg[^>]*>)'
                injection = f'\n<defs><style>\n/* LOD visibility (zoom: {zoom:.2f}) */\n{css_rules}\n</style></defs>'
                svg_content = re.sub(svg_pattern, r'\1' + injection, svg_content, count=1)

        return svg_content

    def should_update(self, new_zoom: float, threshold: float = 0.02) -> bool:
        """
        Check if zoom has changed enough to warrant a CSS update.

        For continuous LOD, we need to update more frequently during
        transitions, but can skip updates when fully in a stable zone.

        Args:
            new_zoom: New zoom level
            threshold: Minimum zoom change ratio to trigger update

        Returns:
            True if CSS should be regenerated
        """
        if self._last_zoom == 0:
            return True

        # Calculate relative change
        change_ratio = abs(new_zoom - self._last_zoom) / max(self._last_zoom, 0.01)

        # During transitions, be more sensitive
        opacities = self.calculate_all_opacities(new_zoom)
        in_transition = any(0.05 < op < 0.95 for op in opacities.values())

        if in_transition:
            threshold = 0.01  # More sensitive during transitions

        return change_ratio > threshold

    def update(self, zoom: float) -> Tuple[int, bool]:
        """
        Update LOD based on zoom and return dominant level.

        Args:
            zoom: Current zoom level

        Returns:
            Tuple of (dominant_lod, should_reload)
        """
        should_reload = self.should_update(zoom)
        self._last_zoom = zoom

        dominant_lod = self.get_dominant_lod(zoom)
        return dominant_lod, should_reload
