"""
Sync module - DEPRECATED

LiveSync and VulkanSync are no longer used.
The embedded VulkanViewportWidget handles 3D updates directly via DLL.

These modules are kept for reference but not imported.
"""

# Disabled - not needed with embedded Vulkan viewport
HAS_LIVESYNC = False
HAS_VULKAN_SYNC = False

def get_livesync_server():
    return None

def get_vulkan_sync_client():
    return None
