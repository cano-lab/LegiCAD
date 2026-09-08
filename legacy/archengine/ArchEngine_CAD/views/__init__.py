"""View components for 2D visualization"""
# Lazy imports to avoid circular dependencies

def get_sheet_view():
    """Lazy import for SheetView."""
    from views.sheet_view import SheetView, SheetViewContainer
    return SheetView, SheetViewContainer
