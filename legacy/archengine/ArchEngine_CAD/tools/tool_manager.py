"""
Tool Manager - handles tool switching and dispatching
"""
from typing import Optional, Dict, Type

from PyQt6.QtCore import QObject, pyqtSignal

from tools.base_tool import BaseTool, ToolType
from tools.select_tool import SelectTool
from core.events import event_bus


class ToolManager(QObject):
    """
    Manages the active tool and handles tool switching.
    """

    tool_changed = pyqtSignal(str)  # tool name

    def __init__(self, view, document, parent=None):
        super().__init__(parent)
        self.view = view
        self.document = document

        # Available tools
        self._tools: Dict[ToolType, BaseTool] = {}
        self._active_tool: Optional[BaseTool] = None

        # Register default tools
        self._register_default_tools()

        # Set default tool
        self.set_tool(ToolType.SELECT)

    def _register_default_tools(self):
        """Register the built-in tools."""
        self._tools[ToolType.SELECT] = SelectTool(self.view, self.document)

    def register_tool(self, tool_type: ToolType, tool: BaseTool):
        """Register a custom tool."""
        self._tools[tool_type] = tool

    def get_tool(self, tool_type: ToolType) -> Optional[BaseTool]:
        """Get a tool by type."""
        return self._tools.get(tool_type)

    @property
    def active_tool(self) -> Optional[BaseTool]:
        """Get the currently active tool."""
        return self._active_tool

    def set_tool(self, tool_type: ToolType):
        """Switch to a different tool."""
        if tool_type not in self._tools:
            return

        # Deactivate current tool
        if self._active_tool:
            self._active_tool.deactivate()

        # Activate new tool
        self._active_tool = self._tools[tool_type]
        self._active_tool.activate()

        # Emit signals
        self.tool_changed.emit(self._active_tool.name)
        event_bus.tool_changed.emit(tool_type.value)

    def cancel(self):
        """Cancel current tool operation."""
        if self._active_tool:
            self._active_tool.cancel()
