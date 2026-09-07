"""
Event bus for application-wide signals
"""
from PyQt6.QtCore import QObject, pyqtSignal


class EventBus(QObject):
    """
    Central event bus for application-wide signals.
    Used for communication between components.
    """

    # Document events
    document_loaded = pyqtSignal(str)  # file_path
    document_saved = pyqtSignal(str)   # file_path
    document_modified = pyqtSignal()   # document changed

    # Element events
    element_added = pyqtSignal(str, str, dict)     # element_type, element_id, data
    element_modified = pyqtSignal(str, str, dict)  # element_type, element_id, changes
    element_removed = pyqtSignal(str, str)         # element_type, element_id

    # Selection events
    selection_changed = pyqtSignal(list)  # list of selected element ids
    selection_cleared = pyqtSignal()

    # View events
    view_zoom_changed = pyqtSignal(float)   # zoom level
    view_pan_changed = pyqtSignal(float, float)  # x, y offset

    # Tool events
    tool_changed = pyqtSignal(str)  # tool name
    tool_activated = pyqtSignal(str)
    tool_deactivated = pyqtSignal(str)

    # Status events
    status_message = pyqtSignal(str, int)  # message, timeout_ms

    def __init__(self, parent=None):
        super().__init__(parent)


# Global event bus instance - created lazily
_event_bus = None


def get_event_bus():
    """Get or create the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# For backward compatibility
class EventBusProxy:
    """Proxy that lazily creates the event bus."""
    def __getattr__(self, name):
        return getattr(get_event_bus(), name)


event_bus = EventBusProxy()
