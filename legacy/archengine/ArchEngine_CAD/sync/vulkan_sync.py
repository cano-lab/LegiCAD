"""
VulkanSync - Named pipe client for real-time sync with Vulkan renderer.

Connects to the ArchEngine Vulkan kernel via Windows named pipe for
real-time building visualization. Similar to LiveSync but for the
standalone Vulkan renderer instead of UE5.
"""
import json
import struct
import threading
import logging
from typing import Optional, Callable
from enum import IntEnum

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

# Windows named pipe support
import sys
if sys.platform == 'win32':
    import win32file
    import win32pipe
    import pywintypes
    HAS_WIN32 = True
else:
    HAS_WIN32 = False
    print("[VulkanSync] Windows-only: win32 modules not available")

logger = logging.getLogger(__name__)


class IPCMessageType(IntEnum):
    """Message types matching C++ IPCMessageType enum."""
    Ping = 0
    Pong = 1
    BuildingData = 2
    CameraUpdate = 3
    SelectElement = 4
    Shutdown = 255


class VulkanSyncClient(QObject):
    """
    Named pipe client for syncing building data with Vulkan renderer.

    Usage:
        client = VulkanSyncClient()
        client.connected.connect(lambda: print("Connected!"))
        client.connect_to_renderer()

        # When document changes:
        client.send_building_data(document.get_data())

        # Or connect to document signal:
        document.document_changed.connect(
            lambda: client.send_building_data(doc.get_data())
        )
    """

    # Signals
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_failed = pyqtSignal(str)  # Error message

    def __init__(self, pipe_name: str = "ArchEngine_Kernel", parent=None):
        super().__init__(parent)

        if not HAS_WIN32:
            raise ImportError("win32 modules required. Run: pip install pywin32")

        self.pipe_name = pipe_name
        self._pipe_path = f"\\\\.\\pipe\\{pipe_name}"
        self._pipe = None
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._pending_data: Optional[dict] = None
        self._lock = threading.Lock()

        # Debounce timer for rapid updates
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._flush_pending_data)

        # Reconnection timer
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._auto_reconnect = True
        self._reconnect_interval = 2000  # 2 seconds

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect_to_renderer(self) -> bool:
        """
        Connect to the Vulkan renderer's named pipe.

        Returns True if connection initiated, False if already connected.
        Actual connection result comes via connected/connection_failed signals.
        """
        if self._connected:
            return True

        # Start connection in background thread
        self._running = True
        self._thread = threading.Thread(target=self._connect_thread, daemon=True)
        self._thread.start()
        return True

    def disconnect(self):
        """Disconnect from the Vulkan renderer."""
        self._running = False
        self._auto_reconnect = False
        self._reconnect_timer.stop()

        with self._lock:
            if self._pipe:
                try:
                    win32file.CloseHandle(self._pipe)
                except:
                    pass
                self._pipe = None

        self._connected = False
        if self._thread:
            self._thread.join(timeout=1.0)

        QTimer.singleShot(0, self.disconnected.emit)
        print("[VulkanSync] Disconnected")

    def send_building_data(self, data: dict, debounce_ms: int = 50):
        """
        Send building data to Vulkan renderer.

        Args:
            data: Building JSON (walls_batch, doors, windows, roofs, etc.)
            debounce_ms: Delay before sending (prevents flooding on rapid changes)
        """
        self._pending_data = data
        if not self._send_timer.isActive():
            self._send_timer.start(debounce_ms)

    def send_camera_update(self, yaw: float, pitch: float, distance: float):
        """Send camera position update to renderer."""
        if not self._connected:
            return

        # Pack as 3 floats
        payload = struct.pack('fff', yaw, pitch, distance)
        self._send_message(IPCMessageType.CameraUpdate, payload)

    def send_selection(self, element_ids: list):
        """Send element selection to renderer."""
        if not self._connected:
            return

        payload = json.dumps({"selected": element_ids}).encode('utf-8')
        self._send_message(IPCMessageType.SelectElement, payload)

    def _flush_pending_data(self):
        """Actually send the pending building data (async via thread)."""
        if self._pending_data and self._connected:
            json_str = json.dumps(self._pending_data)
            payload = json_str.encode('utf-8')
            # Send in background thread to avoid blocking UI
            threading.Thread(
                target=self._send_message_async,
                args=(IPCMessageType.BuildingData, payload),
                daemon=True
            ).start()
        self._pending_data = None

    def _send_message_async(self, msg_type: IPCMessageType, payload: bytes):
        """Send message in background thread."""
        if self._send_message(msg_type, payload):
            print(f"[VulkanSync] Sent {msg_type.name} ({len(payload)} bytes)")

    def _send_message(self, msg_type: IPCMessageType, payload: bytes) -> bool:
        """
        Send a message to the renderer.

        Message format (matches C++ IPC server):
        - Header: 2x uint32 (type, payload_length)
        - Payload: raw bytes
        """
        with self._lock:
            if not self._pipe or not self._connected:
                return False

            try:
                # Pack header: type (u32) + length (u32)
                header = struct.pack('II', int(msg_type), len(payload))

                # Write header
                win32file.WriteFile(self._pipe, header)

                # Write payload if any
                if payload:
                    win32file.WriteFile(self._pipe, payload)

                return True

            except pywintypes.error as e:
                print(f"[VulkanSync] Write error: {e}")
                self._handle_disconnect()
                return False

    def _connect_thread(self):
        """Background thread for pipe connection."""
        while self._running:
            try:
                # Try to open the pipe
                pipe = win32file.CreateFile(
                    self._pipe_path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,  # No sharing
                    None,  # Default security
                    win32file.OPEN_EXISTING,
                    0,  # Normal attributes
                    None  # No template
                )

                # Set pipe to message mode
                win32pipe.SetNamedPipeHandleState(
                    pipe,
                    win32pipe.PIPE_READMODE_MESSAGE,
                    None,
                    None
                )

                with self._lock:
                    self._pipe = pipe
                    self._connected = True

                if not hasattr(self, '_connection_logged'):
                    print(f"[VulkanSync] Connected to {self._pipe_path}")
                    self._connection_logged = True
                QTimer.singleShot(0, self.connected.emit)

                # Read loop (for responses from renderer)
                self._read_loop()

            except pywintypes.error as e:
                if e.winerror == 2:  # ERROR_FILE_NOT_FOUND - pipe doesn't exist
                    pass  # Renderer not running yet
                elif e.winerror == 231:  # ERROR_PIPE_BUSY
                    pass  # Another client connected
                else:
                    print(f"[VulkanSync] Connection error: {e}")

                # Wait before retry
                import time
                time.sleep(1.0)

                if not self._running:
                    break

    def _read_loop(self):
        """Read responses from renderer (runs in background thread)."""
        while self._running and self._connected:
            try:
                # Read message header (8 bytes: type + length)
                _, header_data = win32file.ReadFile(self._pipe, 8)
                if len(header_data) < 8:
                    break

                msg_type, payload_len = struct.unpack('II', header_data)

                # Read payload if any
                payload = b''
                if payload_len > 0:
                    _, payload = win32file.ReadFile(self._pipe, payload_len)

                self._handle_response(msg_type, payload)

            except pywintypes.error as e:
                if e.winerror in (109, 232, 233):  # Broken pipe errors
                    break
                print(f"[VulkanSync] Read error: {e}")
                break

        self._handle_disconnect()

    def _handle_response(self, msg_type: int, payload: bytes):
        """Handle response message from renderer."""
        if msg_type == IPCMessageType.Pong:
            print("[VulkanSync] Received pong")
        elif msg_type == IPCMessageType.SelectElement:
            # Renderer sent selection update
            try:
                data = json.loads(payload.decode('utf-8'))
                selected = data.get('selected', [])
                print(f"[VulkanSync] Renderer selection: {selected}")
            except:
                pass

    def _handle_disconnect(self):
        """Handle pipe disconnection."""
        was_connected = self._connected

        with self._lock:
            self._connected = False
            if self._pipe:
                try:
                    win32file.CloseHandle(self._pipe)
                except:
                    pass
                self._pipe = None

        if was_connected:
            # Only log first disconnect to reduce spam
            if not hasattr(self, '_disconnect_logged'):
                print("[VulkanSync] Connection lost (kernel not running)")
                self._disconnect_logged = True
            QTimer.singleShot(0, self.disconnected.emit)

            # Start auto-reconnect if enabled
            if self._auto_reconnect and self._running:
                QTimer.singleShot(0, lambda: self._reconnect_timer.start(self._reconnect_interval))

    def _try_reconnect(self):
        """Attempt to reconnect."""
        if not self._connected and self._running:
            print("[VulkanSync] Attempting reconnect...")
            self.connect_to_renderer()
        else:
            self._reconnect_timer.stop()


# Singleton instance
_client_instance: Optional[VulkanSyncClient] = None


def get_vulkan_sync_client() -> VulkanSyncClient:
    """Get or create the global VulkanSync client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = VulkanSyncClient()
    return _client_instance
