"""
LiveSync WebSocket Server for UE5 integration.

Hosts a WebSocket server on port 8765 that UE5's ArchLiveSyncComponent connects to.
Sends building geometry when the document changes.
"""
import asyncio
import json
import threading
import logging
from typing import Optional, Set, Any

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    print("[LiveSync] websockets package not installed. Run: pip install websockets")

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)


class LiveSyncServer(QObject):
    """
    WebSocket server for syncing building data with UE5.

    Usage:
        server = LiveSyncServer()
        server.start()

        # When document changes:
        server.send_building_data(document.get_data())

        # Or connect to document signal:
        document.document_changed.connect(lambda: server.send_building_data(doc.get_data()))
    """

    # Signals
    client_connected = pyqtSignal()
    client_disconnected = pyqtSignal()
    message_received = pyqtSignal(str)  # For incoming messages from UE5

    def __init__(self, host: str = "localhost", port: int = 8765, parent=None):
        super().__init__(parent)

        if not HAS_WEBSOCKETS:
            raise ImportError("websockets package required. Run: pip install websockets")

        self.host = host
        self.port = port
        self._clients: Set[WebSocketServerProtocol] = set()
        self._server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._pending_data: Optional[dict] = None

        # Timer to send pending data (avoids flooding)
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._flush_pending_data)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def start(self):
        """Start the WebSocket server in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        print(f"[LiveSync] Server starting on ws://{self.host}:{self.port}")

    def stop(self):
        """Stop the WebSocket server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
        print("[LiveSync] Server stopped")

    def send_building_data(self, data: dict, debounce_ms: int = 100):
        """
        Send building data to all connected UE5 clients.

        Args:
            data: Building JSON (walls_batch, doors, windows, roofs, etc.)
            debounce_ms: Delay before sending (prevents flooding on rapid changes)
        """
        self._pending_data = data
        if not self._send_timer.isActive():
            self._send_timer.start(debounce_ms)

    def _flush_pending_data(self):
        """Actually send the pending data."""
        if self._pending_data and self._clients:
            json_str = json.dumps(self._pending_data)
            asyncio.run_coroutine_threadsafe(
                self._broadcast(json_str),
                self._loop
            )
            print(f"[LiveSync] Sent building data to {len(self._clients)} client(s)")
        self._pending_data = None

    def send_selection(self, selected_ids: list):
        """Send selection sync to UE5."""
        msg = {
            "type": "selection",
            "payload": {
                "selected_ids": selected_ids,
                "source": "cad"
            }
        }
        if self._clients and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(json.dumps(msg)),
                self._loop
            )

    def _run_server(self):
        """Run the async server in a thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[LiveSync] Server error: {e}")
        finally:
            self._loop.close()

    async def _serve(self):
        """Main server coroutine."""
        async with websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=5,
            ping_timeout=10
        ) as server:
            self._server = server
            print(f"[LiveSync] Server running on ws://{self.host}:{self.port}")

            while self._running:
                await asyncio.sleep(0.1)

    async def _handle_client(self, websocket: WebSocketServerProtocol, path: str = ""):
        """Handle a connected client."""
        self._clients.add(websocket)
        print(f"[LiveSync] Client connected ({len(self._clients)} total)")

        # Emit signal on main thread
        QTimer.singleShot(0, self.client_connected.emit)

        # Send current data if available
        if self._pending_data:
            await websocket.send(json.dumps(self._pending_data))

        try:
            async for message in websocket:
                # Handle incoming messages from UE5
                self._handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            print(f"[LiveSync] Client disconnected ({len(self._clients)} remaining)")
            QTimer.singleShot(0, self.client_disconnected.emit)

    def _handle_message(self, message: str):
        """Process incoming message from UE5."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "selection":
                # UE5 sent selection update
                selected = data.get("payload", {}).get("selected_ids", [])
                print(f"[LiveSync] UE5 selection: {selected}")
                QTimer.singleShot(0, lambda: self.message_received.emit(message))

            elif msg_type == "heartbeat":
                # Respond to heartbeat
                if self._loop and self._clients:
                    response = json.dumps({"type": "heartbeat_ack"})
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast(response),
                        self._loop
                    )
            elif msg_type == "view":
                # Camera position from UE5
                print(f"[LiveSync] UE5 camera update")
                QTimer.singleShot(0, lambda: self.message_received.emit(message))

        except json.JSONDecodeError:
            print(f"[LiveSync] Invalid JSON: {message[:100]}")

    async def _broadcast(self, message: str):
        """Send message to all connected clients."""
        if self._clients:
            await asyncio.gather(
                *[client.send(message) for client in self._clients],
                return_exceptions=True
            )


# Singleton instance
_server_instance: Optional[LiveSyncServer] = None


def get_livesync_server() -> LiveSyncServer:
    """Get or create the global LiveSync server instance."""
    global _server_instance
    if _server_instance is None:
        _server_instance = LiveSyncServer()
    return _server_instance
