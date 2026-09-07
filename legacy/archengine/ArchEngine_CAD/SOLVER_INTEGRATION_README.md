# Solver Integration for ArchEngine CAD

This integration connects the new solver suite to the ArchEngine CAD application.

## Files Added

| File | Purpose |
|------|---------|
| `solver_integration.py` | Core integration module with dialogs and workers |
| `solver_menu.py` | Menu and toolbar integration for CAD main window |
| `advanced_solvers.py` | 4 new solvers (Genetic, Annealing, Force-Directed, Space Colonization) |
| `complete_solver_suite.py` | Unified interface for all 9 solvers |
| `visual_comparison.py` | Teaching comparison tool with SVG export |

## Available Solvers (9 Total)

1. **Grid Solver** - Fast grid-based search
2. **Wave Function Collapse** - Organic, emergent patterns
3. **Tree Solver** - Hierarchical slicing
4. **Perfect Adjacency** - Guaranteed relationship satisfaction
5. **Constraint Solver** - Exact CSP
6. **Genetic Algorithm** - Evolutionary optimization
7. **Simulated Annealing** - Thermodynamic cooling
8. **Force-Directed** - Physics simulation
9. **Space Colonization** - Growth-based organic

## Integration Steps

### 1. Add to Main Window

```python
# In your main_window.py
from solver_menu import SolverMenuMixin, SolverToolbarMixin

class MainWindow(QMainWindow, SolverMenuMixin, SolverToolbarMixin):
    def __init__(self):
        super().__init__()
        
        # ... existing init code ...
        
        # Add solver integration
        self.setup_solver_menu()
        self.setup_solver_toolbar()
    
    def refresh_all_views(self):
        """Called after layout generation."""
        self.plan_view.update()
        self.viewport.update()
        # ... etc
```

### 2. Menu Actions

The Solvers menu provides:
- **Generate Layout...** (Ctrl+Shift+G) - Open solver selection dialog
- **Compare All Solvers** - Generate comparison drawing
- **Export Teaching Materials...** - Export visual comparison for teaching
- **About Solvers...** - Show solver information

### 3. Usage Flow

```
User selects "Generate Layout..."
    ↓
SolverSelectionDialog opens
    ↓
User selects algorithm (with descriptions)
    ↓
SolverWorker runs in background thread
    ↓
Layout generated and applied to document
    ↓
Views refreshed
```

## Solver Selection Dialog

The dialog shows:
- Dropdown of all 9 solvers
- Rich description of selected solver
- Characteristics (speed, reliability, best for)
- Progress bar during solving
- Background thread (UI stays responsive)

## Drawing Generation Integration

Solvers feed into the drawing pipeline:

```python
# Generate layout with solver
layout_data = solver_integration.generate_layout(document)

# Use in drawing generation
plan_svg = generate_plan_from_layout(layout_data)
elevation_svg = generate_elevation_from_layout(layout_data)
```

## Teaching Features

For classroom use:

```python
# Generate comparison of all solvers
from visual_comparison import TeachingComparator

comparator = TeachingComparator(graph, width, depth)
results = comparator.compare_all('./output')

# Generates:
# - Individual SVG for each solver
# - Comparison grid
# - Interactive HTML report
# - Teaching notes (markdown)
```

## Visual Debugging

Solvers support animation export:

```python
from advanced_solvers import GeneticSolver

solver = GeneticSolver(graph, width, depth)
solver.enable_visualization = True
layout = solver.solve()

# Export solving process as animated SVG
solver.export_animation_svg('genetic_process.svg')
```

## Testing

Run the solver integration:

```bash
cd ArchEngine_CAD
python solver_integration.py
```

## Troubleshooting

**Solvers not available:**
- Check that `advanced_solvers.py` is in the same directory
- Verify imports: `from complete_solver_suite import CompleteSolverSuite`

**Import errors:**
- Ensure `room_relationships.py` is accessible
- Check that kernel scripts are in Python path

**Layout not applying:**
- Verify document has rooms defined
- Check building bounds are set
- Review console for error messages

## Future Enhancements

- [ ] Real-time solver preview
- [ ] Solver parameter tuning UI
- [ ] Batch processing multiple designs
- [ ] Machine learning-based solver selection
- [ ] 3D visualization of solving process
