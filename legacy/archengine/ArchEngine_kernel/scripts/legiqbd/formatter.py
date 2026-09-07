"""Response formatter for LegiQBD.

Formats conversation responses and design information for display.
Supports multiple output formats: text, markdown, and structured data.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Import QBD
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from qbd import QBDState


class OutputFormat(Enum):
    """Output format options."""
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"


@dataclass
class FormattedOutput:
    """A formatted output block."""
    content: str
    format: OutputFormat
    metadata: Dict[str, Any] = None


class ResponseFormatter:
    """Format responses for display."""

    def __init__(self, format: OutputFormat = OutputFormat.TEXT):
        self.format = format
        self.use_color = True
        self.show_progress = True

    # =========================================================================
    # Main Formatting
    # =========================================================================

    def format_response(
        self,
        text: str,
        fragments_applied: List[Dict] = None,
        errors: List[str] = None,
        questions: List[Dict] = None,
        design_changed: bool = False,
        show_status: bool = True
    ) -> str:
        """Format a complete response.

        Args:
            text: The main response text
            fragments_applied: List of applied fragments
            errors: List of errors
            questions: List of pending questions
            design_changed: Whether the design changed
            show_status: Whether to show status indicators

        Returns:
            Formatted string for display
        """
        lines = []

        # Status indicator
        if show_status and self.show_progress:
            status = self._format_status(fragments_applied, errors, design_changed)
            if status:
                lines.append(status)
                lines.append("")

        # Main text
        lines.append(text)

        # Errors
        if errors:
            lines.append("")
            lines.append(self._format_errors(errors))

        return "\n".join(lines)

    def format_design_summary(self, state: QBDState) -> str:
        """Format a design summary for display."""
        if self.format == OutputFormat.MARKDOWN:
            return self._format_design_markdown(state)
        else:
            return self._format_design_text(state)

    def format_solved_layout(self, layout: Dict[str, Any]) -> str:
        """Format a solved layout for display."""
        if self.format == OutputFormat.MARKDOWN:
            return self._format_layout_markdown(layout)
        else:
            return self._format_layout_text(layout)

    def format_questions(self, questions: List[Dict]) -> str:
        """Format questions for display."""
        if not questions:
            return ""

        lines = []
        for i, q in enumerate(questions, 1):
            lines.append(f"\n{i}. {q.get('text', 'Question')}")

            options = q.get("options", [])
            if options:
                for j, opt in enumerate(options, 1):
                    label = opt.get("label", opt.get("value", ""))
                    desc = opt.get("description", "")
                    if desc:
                        lines.append(f"   {j}) {label} - {desc}")
                    else:
                        lines.append(f"   {j}) {label}")

        return "\n".join(lines)

    # =========================================================================
    # Status Formatting
    # =========================================================================

    def _format_status(
        self,
        fragments: List[Dict] = None,
        errors: List[str] = None,
        design_changed: bool = False
    ) -> str:
        """Format status indicators."""
        indicators = []

        if fragments:
            count = len(fragments)
            if self.use_color:
                indicators.append(f"✓ {count} change{'s' if count != 1 else ''}")
            else:
                indicators.append(f"[+{count}]")

        if errors:
            count = len(errors)
            if self.use_color:
                indicators.append(f"⚠ {count} issue{'s' if count != 1 else ''}")
            else:
                indicators.append(f"[!{count}]")

        if design_changed:
            if self.use_color:
                indicators.append("◉ Design updated")
            else:
                indicators.append("[UPDATED]")

        return " | ".join(indicators) if indicators else ""

    def _format_errors(self, errors: List[str]) -> str:
        """Format error messages."""
        if not errors:
            return ""

        lines = []
        if self.use_color:
            lines.append("⚠ Issues:")
        else:
            lines.append("Issues:")

        for error in errors[:5]:  # Limit to 5
            lines.append(f"  • {error}")

        if len(errors) > 5:
            lines.append(f"  ... and {len(errors) - 5} more")

        return "\n".join(lines)

    # =========================================================================
    # Design Formatting
    # =========================================================================

    def _format_design_text(self, state: QBDState) -> str:
        """Format design as plain text."""
        rooms = state.rooms
        if not rooms:
            return "No rooms defined yet."

        lines = []
        lines.append(f"DESIGN SUMMARY ({len(rooms)} rooms)")
        lines.append("-" * 40)

        # Group rooms by type
        by_type = {}
        for room in rooms:
            rtype = room.get("type", "other")
            by_type.setdefault(rtype, []).append(room)

        for rtype, room_list in by_type.items():
            names = [r["name"] for r in room_list]
            lines.append(f"  {rtype}: {', '.join(names)}")

        # Adjacencies
        adj = state.adjacencies
        if adj:
            lines.append("")
            lines.append(f"CONNECTIONS ({len(adj)})")
            for a in adj[:8]:
                conn_type = a.get("connection_type", "door")
                lines.append(f"  {a['room_a'][-8:]} <-> {a['room_b'][-8:]} ({conn_type})")

        # Constraints
        constraints = state.constraints
        active = {k: v for k, v in constraints.items() if v is not None}
        if active:
            lines.append("")
            lines.append("CONSTRAINTS")
            for k, v in active.items():
                lines.append(f"  {k}: {v}")

        return "\n".join(lines)

    def _format_design_markdown(self, state: QBDState) -> str:
        """Format design as markdown."""
        rooms = state.rooms
        if not rooms:
            return "*No rooms defined yet.*"

        lines = []
        lines.append(f"## Design Summary ({len(rooms)} rooms)")
        lines.append("")

        # Group rooms by type
        by_type = {}
        for room in rooms:
            rtype = room.get("type", "other")
            by_type.setdefault(rtype, []).append(room)

        for rtype, room_list in by_type.items():
            names = [r["name"] for r in room_list]
            lines.append(f"- **{rtype}**: {', '.join(names)}")

        # Adjacencies
        adj = state.adjacencies
        if adj:
            lines.append("")
            lines.append(f"### Connections ({len(adj)})")
            for a in adj[:8]:
                conn = a.get("connection_type", "door")
                lines.append(f"- {a['room_a'][-8:]} ↔ {a['room_b'][-8:]} ({conn})")

        return "\n".join(lines)

    def _format_layout_text(self, layout: Dict[str, Any]) -> str:
        """Format solved layout as text."""
        lines = []
        lines.append("SOLVED LAYOUT")
        lines.append("=" * 40)

        # Rooms with positions
        rooms = layout.get("rooms", [])
        if rooms:
            lines.append("\nROOMS:")
            for room in rooms:
                name = room.get("name", "Unknown")
                pos = room.get("position", {})
                size = room.get("size", {})
                x, y = pos.get("x", 0), pos.get("y", 0)
                w, h = size.get("width", 0), size.get("depth", 0)
                lines.append(f"  {name}: ({x:.1f}, {y:.1f}) - {w:.1f}m x {h:.1f}m")

        # Metrics
        metrics = layout.get("metrics", {})
        if metrics:
            lines.append("\nMETRICS:")
            for key, value in metrics.items():
                if isinstance(value, float):
                    lines.append(f"  {key}: {value:.2f}")
                else:
                    lines.append(f"  {key}: {value}")

        # Score
        score = layout.get("score")
        if score is not None:
            lines.append(f"\nSCORE: {score:.1f}/10")

        return "\n".join(lines)

    def _format_layout_markdown(self, layout: Dict[str, Any]) -> str:
        """Format solved layout as markdown."""
        lines = []
        lines.append("## Solved Layout")
        lines.append("")

        # Rooms
        rooms = layout.get("rooms", [])
        if rooms:
            lines.append("### Rooms")
            lines.append("| Room | Position | Size |")
            lines.append("|------|----------|------|")
            for room in rooms:
                name = room.get("name", "Unknown")
                pos = room.get("position", {})
                size = room.get("size", {})
                x, y = pos.get("x", 0), pos.get("y", 0)
                w, h = size.get("width", 0), size.get("depth", 0)
                lines.append(f"| {name} | ({x:.1f}, {y:.1f}) | {w:.1f}m × {h:.1f}m |")

        # Score
        score = layout.get("score")
        if score is not None:
            lines.append("")
            lines.append(f"**Score**: {score:.1f}/10")

        return "\n".join(lines)

    # =========================================================================
    # Progress Bar
    # =========================================================================

    def format_progress(
        self,
        phase: str,
        is_solvable: bool,
        is_solved: bool,
        room_count: int
    ) -> str:
        """Format a progress indicator."""
        phases = ["greeting", "discovery", "refining", "solving", "reviewing", "complete"]

        try:
            current_idx = phases.index(phase)
        except ValueError:
            current_idx = 0

        if self.use_color:
            bar = ""
            for i, p in enumerate(phases):
                if i < current_idx:
                    bar += "●─"
                elif i == current_idx:
                    bar += "◉─"
                else:
                    bar += "○─"
            bar = bar.rstrip("─")

            status = f"Phase: {phase.upper()}"
            if room_count > 0:
                status += f" | Rooms: {room_count}"
            if is_solvable:
                status += " | Ready to solve"
            if is_solved:
                status += " | ✓ SOLVED"

            return f"{bar}\n{status}"
        else:
            return f"[{phase.upper()}] Rooms: {room_count} | Solvable: {is_solvable} | Solved: {is_solved}"


# =============================================================================
# Helper Functions
# =============================================================================

def format_response(text: str, **kwargs) -> str:
    """Convenience function to format a response."""
    formatter = ResponseFormatter()
    return formatter.format_response(text, **kwargs)


def format_design(state: QBDState, markdown: bool = False) -> str:
    """Convenience function to format design summary."""
    fmt = OutputFormat.MARKDOWN if markdown else OutputFormat.TEXT
    formatter = ResponseFormatter(format=fmt)
    return formatter.format_design_summary(state)


def format_layout(layout: Dict[str, Any], markdown: bool = False) -> str:
    """Convenience function to format solved layout."""
    fmt = OutputFormat.MARKDOWN if markdown else OutputFormat.TEXT
    formatter = ResponseFormatter(format=fmt)
    return formatter.format_solved_layout(layout)
