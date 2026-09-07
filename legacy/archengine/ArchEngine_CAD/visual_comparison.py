"""
Visual Solver Comparison Tool for Teaching

Interactive SVG-based comparison of all solvers.
Perfect for demonstrating algorithm differences to students.
"""

from typing import Dict, List, Optional
import json
from dataclasses import dataclass

from solver_suite import SolverType, PlacedLayout, SOLVER_INFO
from room_relationships import SpatialGraph


@dataclass
class SolverVisualization:
    """Visualization data for a solver."""
    name: str
    color: str
    description: str
    algorithm_type: str


VISUALIZATION_CONFIG = {
    SolverType.GRID: SolverVisualization(
        name="Grid Solver",
        color="#4CAF50",
        description="Backtracking search on regular grid",
        algorithm_type="Search"
    ),
    SolverType.WAVE_COLLAPSE: SolverVisualization(
        name="Wave Function Collapse",
        color="#9C27B0",
        description="Quantum-inspired collapse from superposition",
        algorithm_type="Constraint Propagation"
    ),
    SolverType.TREE: SolverVisualization(
        name="Tree Solver",
        color="#2196F3",
        description="Hierarchical slicing tree decomposition",
        algorithm_type="Divide & Conquer"
    ),
    SolverType.PERFECT_ADJACENCY: SolverVisualization(
        name="Perfect Adjacency",
        color="#FF9800",
        description="Graph-theoretic rectangular duals",
        algorithm_type="Graph Theory"
    ),
    SolverType.CONSTRAINT: SolverVisualization(
        name="Constraint Solver",
        color="#f44336",
        description="Exact CSP with backtracking",
        algorithm_type="Constraint Satisfaction"
    ),
    SolverType.GENETIC: SolverVisualization(
        name="Genetic Algorithm",
        color="#E91E63",
        description="Evolutionary optimization with selection & mutation",
        algorithm_type="Evolutionary"
    ),
    SolverType.ANNEALING: SolverVisualization(
        name="Simulated Annealing",
        color="#00BCD4",
        description="Thermodynamic cooling to global optimum",
        algorithm_type="Stochastic Optimization"
    ),
    SolverType.FORCE_DIRECTED: SolverVisualization(
        name="Force-Directed",
        color="#FFEB3B",
        description="Physics simulation with springs & repulsion",
        algorithm_type="Physics Simulation"
    ),
    SolverType.SPACE_COLONIZATION: SolverVisualization(
        name="Space Colonization",
        color="#8BC34A",
        description="Organic growth inspired by leaf venation",
        algorithm_type="Growth-Based"
    ),
}


class TeachingComparator:
    """Generate teaching materials comparing solvers."""
    
    def __init__(self, graph: SpatialGraph, width: float, depth: float):
        self.graph = graph
        self.width = width
        self.depth = depth
        self.suite = SolverSuite(graph, width, depth)
    
    def compare_all(self, output_dir: str = "./teaching_output"):
        """Run all solvers and generate comparison materials."""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        results = {}
        
        print("Running all solvers for comparison...")
        print("=" * 60)
        
        for solver_type in SolverType:
            if solver_type == SolverType.HYBRID:
                continue
            
            viz = VISUALIZATION_CONFIG.get(solver_type)
            print(f"\n🔄 Running {viz.name if viz else solver_type.value}...")
            
            try:
                layout = self.suite.solve(solver_type, max_iterations=5000)
                results[solver_type] = layout
                
                # Generate individual visualization
                self._generate_solver_viz(layout, solver_type, f"{output_dir}/{solver_type.value}.svg")
                
                print(f"   ✅ Score: {layout.score:.1f}, Rooms: {len(layout.rooms)}/{len(self.graph.rooms)}")
                
            except Exception as e:
                print(f"   ❌ Failed: {e}")
        
        # Generate comparison materials
        self._generate_comparison_grid(results, f"{output_dir}/comparison_grid.svg")
        self._generate_interactive_html(results, f"{output_dir}/index.html")
        self._generate_teaching_notes(results, f"{output_dir}/teaching_notes.md")
        
        print("\n" + "=" * 60)
        print(f"Teaching materials generated in {output_dir}/")
        
        return results
    
    def _generate_solver_viz(self, layout, solver_type: SolverType, filepath: str):
        """Generate individual solver visualization."""
        viz = VISUALIZATION_CONFIG.get(solver_type)
        color = viz.color if viz else "#666"
        
        scale = 600 / max(self.width, self.depth)
        
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="700" height="650" xmlns="http://www.w3.org/2000/svg">
  <rect width="100%" height="100%" fill="#fafafa"/>
  
  <!-- Title -->
  <text x="350" y="30" text-anchor="middle" font-size="18" font-weight="bold" fill="#333">
    {viz.name if viz else solver_type.value}
  </text>
  <text x="350" y="50" text-anchor="middle" font-size="12" fill="#666">
    {viz.description if viz else ""}
  </text>
  <text x="350" y="70" text-anchor="middle" font-size="11" fill="#999">
    Type: {viz.algorithm_type if viz else "Unknown"} | 
    Score: {layout.score:.1f} | 
    Rooms: {len(layout.rooms)}/{len(self.graph.rooms)}
  </text>
  
  <!-- Layout area -->
  <g transform="translate(50, 100) scale({scale})">
    <rect x="0" y="0" width="{self.width}" height="{self.depth}" 
          fill="white" stroke="#333" stroke-width="0.5"/>
'''
        
        # Draw rooms
        for i, (room_id, room) in enumerate(layout.rooms.items()):
            r = room.rect
            opacity = 0.7
            
            svg += f'''
    <rect x="{r.x}" y="{r.y}" width="{r.width}" height="{r.height}"
          fill="{color}" fill-opacity="{opacity}" 
          stroke="#333" stroke-width="0.3" rx="1"/>
    <text x="{r.center.x}" y="{r.center.y}" 
          text-anchor="middle" dominant-baseline="middle"
          font-size="3" fill="white" font-weight="bold">{room_id[:6]}</text>
'''
        
        svg += '''
  </g>
</svg>'''
        
        with open(filepath, 'w') as f:
            f.write(svg)
    
    def _generate_comparison_grid(self, results: Dict, filepath: str):
        """Generate grid comparing all solvers."""
        
        cols = 3
        rows = (len(results) + cols - 1) // cols
        
        cell_width = 300
        cell_height = 250
        total_width = cols * cell_width + 50
        total_height = rows * cell_height + 100
        
        scale = 200 / max(self.width, self.depth)
        
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{total_width}" height="{total_height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="100%" height="100%" fill="#f5f5f5"/>
  
  <text x="{total_width/2}" y="40" text-anchor="middle" font-size="24" font-weight="bold" fill="#333">
    QBD Solver Comparison
  </text>
'''
        
        solver_list = list(results.items())
        
        for idx, (solver_type, layout) in enumerate(solver_list):
            row = idx // cols
            col = idx % cols
            
            x = 25 + col * cell_width
            y = 80 + row * cell_height
            
            viz = VISUALIZATION_CONFIG.get(solver_type)
            color = viz.color if viz else "#666"
            
            # Cell background
            svg += f'''
  <rect x="{x}" y="{y}" width="{cell_width-10}" height="{cell_height-10}" 
        fill="white" stroke="#ddd" stroke-width="1" rx="5"/>
'''
            
            # Title
            svg += f'''
  <text x="{x + (cell_width-10)/2}" y="{y + 20}" text-anchor="middle" 
        font-size="14" font-weight="bold" fill="#333">{viz.name if viz else solver_type.value}</text>
'''
            
            # Mini layout
            svg += f'''
  <g transform="translate({x + 10}, {y + 35}) scale({scale})">
    <rect x="0" y="0" width="{self.width}" height="{self.depth}" 
          fill="white" stroke="#ccc" stroke-width="0.5"/>
'''
            
            for room_id, room in layout.rooms.items():
                r = room.rect
                svg += f'''
    <rect x="{r.x}" y="{r.y}" width="{r.width}" height="{r.height}"
          fill="{color}" fill-opacity="0.6" stroke="none"/>
'''
            
            svg += '''
  </g>
'''
            
            # Stats
            svg += f'''
  <text x="{x + 10}" y="{y + cell_height - 35}" font-size="10" fill="#666">
    Score: {layout.score:.0f}
  </text>
  <text x="{x + 10}" y="{y + cell_height - 20}" font-size="10" fill="#666">
    Rooms: {len(layout.rooms)}/{len(self.graph.rooms)}
  </text>
'''
        
        svg += '</svg>'
        
        with open(filepath, 'w') as f:
            f.write(svg)
    
    def _generate_interactive_html(self, results: Dict, filepath: str):
        """Generate interactive HTML comparison."""
        
        html = '''<!DOCTYPE html>
<html>
<head>
    <title>QBD Solver Comparison - Teaching Tool</title>
    <style>
        body { font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        h1 { text-align: center; color: #333; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; }
        .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .card h3 { margin-top: 0; color: #2c3e50; }
        .card .meta { color: #666; font-size: 14px; margin-bottom: 15px; }
        .svg-container { background: #fafafa; border-radius: 5px; padding: 10px; }
        .stats { display: flex; gap: 20px; margin-top: 15px; }
        .stat { text-align: center; }
        .stat-value { font-size: 24px; font-weight: bold; color: #4CAF50; }
        .stat-label { font-size: 12px; color: #999; }
        .algorithm-tag { display: inline-block; padding: 4px 8px; border-radius: 4px; 
                        font-size: 12px; font-weight: bold; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>🏗️ QBD Solver Comparison for Teaching</h1>
    <div class="grid">
'''
        
        for solver_type, layout in results.items():
            viz = VISUALIZATION_CONFIG.get(solver_type)
            
            html += f'''
        <div class="card">
            <span class="algorithm-tag" style="background: {viz.color if viz else '#666'}20; color: {viz.color if viz else '#666'};">
                {viz.algorithm_type if viz else 'Unknown'}
            </span>
            <h3>{viz.name if viz else solver_type.value}</h3>
            <div class="meta">{viz.description if viz else ''}</div>
            
            <div class="svg-container">
                <img src="{solver_type.value}.svg" width="100%" alt="{viz.name if viz else solver_type.value} result">
            </div>
            
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{layout.score:.0f}</div>
                    <div class="stat-label">Score</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(layout.rooms)}</div>
                    <div class="stat-label">Rooms Placed</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(layout.rooms)/len(self.graph.rooms)*100:.0f}%</div>
                    <div class="stat-label">Completeness</div>
                </div>
            </div>
        </div>
'''
        
        html += '''
    </div>
    
    <div style="margin-top: 40px; padding: 20px; background: white; border-radius: 10px;">
        <h2>📚 Teaching Notes</h2>
        <p><strong>Grid Solver:</strong> Best for introducing algorithmic thinking. Shows backtracking and constraint handling.</p>
        <p><strong>Wave Function Collapse:</strong> Demonstrates emergent behavior from simple rules. Great for discussing complexity.</p>
        <p><strong>Tree Solver:</strong> Illustrates divide-and-conquer and hierarchical decomposition.</p>
        <p><strong>Perfect Adjacency:</strong> Shows graph theory applications. Guarantees vs heuristics.</p>
        <p><strong>Genetic Algorithm:</strong> Evolution in action. Population-based search and fitness landscapes.</p>
        <p><strong>Simulated Annealing:</strong> Thermodynamics metaphor. Escaping local optima.</p>
        <p><strong>Force-Directed:</strong> Physics simulation. Springs, repulsion, equilibrium.</p>
        <p><strong>Space Colonization:</strong> Organic growth processes. Nature-inspired algorithms.</p>
    </div>
</body>
</html>'''
        
        with open(filepath, 'w') as f:
            f.write(html)
    
    def _generate_teaching_notes(self, results: Dict, filepath: str):
        """Generate teaching notes markdown."""
        
        md = '''# QBD Solver Teaching Notes

## Overview

This comparison demonstrates 9 different algorithms for architectural space planning.
Each algorithm embodies different computational thinking approaches.

## Solver Characteristics

'''
        
        for solver_type, layout in results.items():
            viz = VISUALIZATION_CONFIG.get(solver_type)
            
            md += f'''
### {viz.name if viz else solver_type.value}

**Algorithm Type:** {viz.algorithm_type if viz else 'Unknown'}

**Description:** {viz.description if viz else 'N/A'}

**Performance on this problem:**
- Score: {layout.score:.1f}/100
- Rooms placed: {len(layout.rooms)}/{len(self.graph.rooms)}
- Completeness: {len(layout.rooms)/len(self.graph.rooms)*100:.1f}%

**Teaching Points:**
'''
            
            if solver_type == SolverType.GRID:
                md += '- Backtracking search\n- Constraint propagation\n- Heuristic ordering\n'
            elif solver_type == SolverType.WAVE_COLLAPSE:
                md += '- Emergent behavior\n- Local constraints, global patterns\n- Entropy minimization\n'
            elif solver_type == SolverType.TREE:
                md += '- Hierarchical decomposition\n- Divide and conquer\n- Recursive structures\n'
            elif solver_type == SolverType.PERFECT_ADJACENCY:
                md += '- Graph theory\n- Rectangular duals\n- Guaranteed satisfaction\n'
            elif solver_type == SolverType.GENETIC:
                md += '- Evolutionary computation\n- Fitness landscapes\n- Selection pressure\n'
            elif solver_type == SolverType.ANNEALING:
                md += '- Thermodynamic analogy\n- Escaping local optima\n- Cooling schedules\n'
            elif solver_type == SolverType.FORCE_DIRECTED:
                md += '- Physics simulation\n- Spring systems\n- Equilibrium states\n'
            elif solver_type == SolverType.SPACE_COLONIZATION:
                md += '- Growth processes\n- Organic patterns\n- Competition for resources\n'
            
            md += '\n'
        
        md += '''## Discussion Questions

1. Which solver produced the most "architectural" layout? Why?

2. How do the different algorithms handle the adjacency constraints?

3. What are the trade-offs between speed and quality?

4. Which algorithm would you choose for:
   - Quick exploration?
   - Final presentation?
   - Complex adjacency requirements?
   - Organic/natural forms?

5. How might these algorithms inform design thinking beyond computation?

## Student Exercise

Have students:
1. Run all solvers on their own design problem
2. Analyze the differences in output
3. Propose hybrid approaches
4. Design their own algorithm variant
'''
        
        with open(filepath, 'w') as f:
            f.write(md)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def generate_teaching_materials(graph: SpatialGraph, width: float, depth: float, 
                                 output_dir: str = "./teaching_output"):
    """Generate all teaching materials."""
    comparator = TeachingComparator(graph, width, depth)
    return comparator.compare_all(output_dir)


if __name__ == "__main__":
    print("Teaching comparison tool loaded.")
    print("\nUsage:")
    print("  from visual_comparison import TeachingComparator")
    print("  comparator = TeachingComparator(graph, width, depth)")
    print("  results = comparator.compare_all('./output')")
    print("\nGenerates:")
    print("  - Individual solver visualizations")
    print("  - Comparison grid")
    print("  - Interactive HTML")
    print("  - Teaching notes")
