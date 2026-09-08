"""
Solver Menu Integration for ArchEngine CAD

Adds solver actions to the CAD application menu system.
"""

from PyQt6.QtWidgets import (
    QMenu, QAction, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from solver_integration import (
    SolverSelectionDialog, 
    SolverDocumentIntegration,
    generate_solver_comparison,
    SOLVERS_AVAILABLE
)


class SolverMenuMixin:
    """Mixin to add solver menu to CAD main window."""
    
    def setup_solver_menu(self):
        """Set up the solver menu. Call from main window init."""
        if not hasattr(self, 'menubar'):
            return
        
        # Create Solver menu
        solver_menu = self.menubar.addMenu("Sol&vers")
        
        # Generate Layout action
        self.action_generate_layout = QAction("&Generate Layout...", self)
        self.action_generate_layout.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.action_generate_layout.setStatusTip("Generate building layout using selected solver")
        self.action_generate_layout.triggered.connect(self.on_generate_layout)
        solver_menu.addAction(self.action_generate_layout)
        
        # Compare Solvers action
        self.action_compare_solvers = QAction("&Compare All Solvers", self)
        self.action_compare_solvers.setStatusTip("Generate comparison of all solver algorithms")
        self.action_compare_solvers.triggered.connect(self.on_compare_solvers)
        solver_menu.addAction(self.action_compare_solvers)
        
        solver_menu.addSeparator()
        
        # Export for Teaching action
        self.action_export_teaching = QAction("&Export Teaching Materials...", self)
        self.action_export_teaching.setStatusTip("Export solver comparison for teaching")
        self.action_export_teaching.triggered.connect(self.on_export_teaching)
        solver_menu.addAction(self.action_export_teaching)
        
        # Add separator and info
        solver_menu.addSeparator()
        
        self.action_solver_info = QAction("&About Solvers...", self)
        self.action_solver_info.triggered.connect(self.on_solver_info)
        solver_menu.addAction(self.action_solver_info)
        
        # Disable if solvers not available
        if not SOLVERS_AVAILABLE:
            self.action_generate_layout.setEnabled(False)
            self.action_compare_solvers.setEnabled(False)
            self.action_export_teaching.setEnabled(False)
            self.action_generate_layout.setText("Generate Layout (Not Available)")
    
    def on_generate_layout(self):
        """Handle Generate Layout action."""
        if not hasattr(self, 'document'):
            QMessageBox.warning(self, "No Document", "Please create or open a document first.")
            return
        
        if not SOLVERS_AVAILABLE:
            QMessageBox.warning(self, "Solvers Not Available", 
                              "The solver module is not available. Please check installation.")
            return
        
        # Show solver dialog
        integration = SolverDocumentIntegration(self.document)
        success = integration.generate_layout_with_solver(parent_widget=self)
        
        if success:
            # Refresh views
            self.refresh_all_views()
            self.statusBar().showMessage("Layout generated successfully", 3000)
    
    def on_compare_solvers(self):
        """Handle Compare Solvers action."""
        if not hasattr(self, 'document'):
            QMessageBox.warning(self, "No Document", "Please create or open a document first.")
            return
        
        if not SOLVERS_AVAILABLE:
            QMessageBox.warning(self, "Solvers Not Available",
                              "The solver module is not available.")
            return
        
        # Generate comparison
        self.statusBar().showMessage("Running all solvers for comparison...")
        
        try:
            svg_content = generate_solver_comparison(self.document)
            
            if svg_content:
                # Save to file
                filepath, _ = QFileDialog.getSaveFileName(
                    self, "Save Solver Comparison", 
                    "solver_comparison.svg",
                    "SVG Files (*.svg)"
                )
                
                if filepath:
                    with open(filepath, 'w') as f:
                        f.write(svg_content)
                    
                    QMessageBox.information(self, "Comparison Generated",
                                          f"Solver comparison saved to:\n{filepath}")
                    self.statusBar().showMessage("Comparison generated", 3000)
            else:
                QMessageBox.warning(self, "Generation Failed",
                                  "Failed to generate solver comparison.")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate comparison:\n{str(e)}")
    
    def on_export_teaching(self):
        """Handle Export Teaching Materials action."""
        if not hasattr(self, 'document'):
            QMessageBox.warning(self, "No Document", "Please create or open a document first.")
            return
        
        # Select output directory
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Directory for Teaching Materials"
        )
        
        if not output_dir:
            return
        
        try:
            from visual_comparison import TeachingComparator
            
            # Get building bounds
            bounds = self.document.get_building_bounds()
            width = bounds.get("width", 10000) / 1000
            depth = bounds.get("depth", 10000) / 1000
            
            # Build graph
            from room_relationships import SpatialGraph
            graph = SpatialGraph()
            for room_id, room_data in self.document.rooms.items():
                graph.add_room(
                    room_id=room_id,
                    room_type=room_data.get("type", "room"),
                    min_area=room_data.get("area", 100),
                )
            
            # Generate materials
            comparator = TeachingComparator(graph, width, depth)
            comparator.compare_all(output_dir)
            
            QMessageBox.information(
                self, "Teaching Materials Exported",
                f"Teaching materials exported to:\n{output_dir}\n\n"
                "Includes:\n"
                "- Individual solver visualizations\n"
                "- Comparison grid\n"
                "- Interactive HTML report\n"
                "- Teaching notes"
            )
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Export failed:\n{str(e)}")
    
    def on_solver_info(self):
        """Show solver information dialog."""
        if not SOLVERS_AVAILABLE:
            QMessageBox.information(
                self, "About Solvers",
                "Solver Module Status: Not Available\n\n"
                "The solver integration module provides access to 9 different "
                "algorithms for architectural space planning.\n\n"
                "Please ensure the solver modules are properly installed."
            )
            return
        
        from solver_suite import SOLVER_INFO, SolverType
        
        info_text = "<h2>Available Solvers</h2>"
        info_text += "<p>The following solver algorithms are available:</p><ul>"
        
        for solver_type in SolverType:
            if solver_type == SolverType.HYBRID:
                continue
            
            info = SOLVER_INFO.get(solver_type)
            if info:
                info_text += f"<li><b>{info.name}</b> - {info.description}</li>"
        
        info_text += "</ul>"
        info_text += "<p>Select 'Generate Layout' from the Solvers menu to try them out!</p>"
        
        QMessageBox.information(self, "About Solvers", info_text)
    
    def refresh_all_views(self):
        """Refresh all document views. Override in main window."""
        # This should be implemented in the main window class
        pass


# =============================================================================
# TOOLBAR INTEGRATION
# =============================================================================

class SolverToolbarMixin:
    """Mixin to add solver toolbar buttons."""
    
    def setup_solver_toolbar(self):
        """Set up solver toolbar."""
        if not hasattr(self, 'toolbar'):
            return
        
        # Add separator
        self.toolbar.addSeparator()
        
        # Generate Layout button
        self.btn_generate_layout = self.toolbar.addAction("Generate Layout")
        self.btn_generate_layout.setStatusTip("Generate layout with solver (Ctrl+Shift+G)")
        self.btn_generate_layout.triggered.connect(self.on_generate_layout)
        
        if not SOLVERS_AVAILABLE:
            self.btn_generate_layout.setEnabled(False)


# =============================================================================
# USAGE INSTRUCTIONS
# =============================================================================
"""
To integrate into CAD main window:

1. Import the mixins:
   from solver_menu import SolverMenuMixin, SolverToolbarMixin

2. Add to class inheritance:
   class MainWindow(QMainWindow, SolverMenuMixin, SolverToolbarMixin):

3. Call setup in __init__:
   self.setup_solver_menu()
   self.setup_solver_toolbar()

4. Implement refresh_all_views() method in MainWindow
"""

if __name__ == "__main__":
    print("Solver menu integration module loaded.")
    print("Import SolverMenuMixin and SolverToolbarMixin to add to CAD.")
