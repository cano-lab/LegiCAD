"""
ArchEngine Viewport - 3D Visualization Module

Provides the VulkanViewportWidget for embedding 3D visualization in PyQt6.
Uses ctypes to call into ArchEngineLib.dll for real-time Vulkan rendering.
"""

# Vulkan widget (the only viewport we use)
try:
    from .vulkan_widget import VulkanViewportWidget
    HAS_VULKAN_WIDGET = True
except ImportError as e:
    HAS_VULKAN_WIDGET = False
    print(f"[viewport] VulkanViewportWidget not available: {e}")

__all__ = ['VulkanViewportWidget', 'HAS_VULKAN_WIDGET']
