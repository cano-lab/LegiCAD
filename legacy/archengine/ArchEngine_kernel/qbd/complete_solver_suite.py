"""
Complete Solver Suite with All Algorithms

Imports and registers all solvers from solver_suite and advanced_solvers.
"""

# Import base from solver_suite
from solver_suite import (
    SolverType, SolverMetadata, SOLVER_INFO,
    BaseSolver, PlacedLayout, PlacedRoom, Rect, Point,
    GridSolverWrapper, WaveCollapseSolver, TreeSolver,
    PerfectAdjacencySolver, ConstraintSolver, HybridSolver
)

# Import advanced solvers
try:
    from advanced_solvers import (
        GeneticSolver, SimulatedAnnealingSolver,
        ForceDirectedSolver, SpaceColonizationSolver
    )
    ADVANCED_AVAILABLE = True
except ImportError:
    ADVANCED_AVAILABLE = False

# Update SOLVER_MAP
SOLVER_MAP = {
    SolverType.GRID: GridSolverWrapper,
    SolverType.WAVE_COLLAPSE: WaveCollapseSolver,
    SolverType.TREE: TreeSolver,
    SolverType.PERFECT_ADJACENCY: PerfectAdjacencySolver,
    SolverType.CONSTRAINT: ConstraintSolver,
    SolverType.HYBRID: HybridSolver,
}

if ADVANCED_AVAILABLE:
    SOLVER_MAP.update({
        SolverType.GENETIC: GeneticSolver,
        SolverType.ANNEALING: SimulatedAnnealingSolver,
        SolverType.FORCE_DIRECTED: ForceDirectedSolver,
        SolverType.SPACE_COLONIZATION: SpaceColonizationSolver,
    })


class CompleteSolverSuite:
    """Complete solver suite with all algorithms."""
    
    def __init__(self, graph, width, depth, grid_size=2.0):
        from room_relationships import SpatialGraph
        self.graph = graph
        self.width = width
        self.depth = depth
        self.grid_size = grid_size
    
    def get_available_solvers(self):
        """Get all available solvers."""
        return [(st, SOLVER_INFO[st]) for st in SolverType]
    
    def get_solver_metadata(self, solver_type):
        """Get metadata for solver."""
        return SOLVER_INFO[solver_type]
    
    def solve(self, solver_type, max_iterations=10000):
        """Solve with specified solver."""
        solver_class = SOLVER_MAP.get(solver_type)
        if not solver_class:
            raise ValueError(f"Unknown solver: {solver_type}")
        
        solver = solver_class(self.graph, self.width, self.depth, self.grid_size)
        return solver.solve(max_iterations)
    
    def solve_all(self, max_iterations=5000):
        """Run all solvers."""
        results = {}
        for solver_type in SolverType:
            if solver_type == SolverType.HYBRID:
                continue
            try:
                results[solver_type] = self.solve(solver_type, max_iterations)
            except Exception as e:
                print(f"Solver {solver_type.value} failed: {e}")
        return results


# Backwards compatibility
SolverSuite = CompleteSolverSuite


if __name__ == "__main__":
    print("Complete Solver Suite loaded.")
    print(f"\nAvailable solvers ({len(SOLVER_MAP)}):")
    for st in SolverType:
        info = SOLVER_INFO.get(st)
        if info:
            print(f"  - {info.name} ({st.value})")
