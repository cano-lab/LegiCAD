"""
Solver CLI - Command-line interface for room layout solvers

Usage:
    python solver_cli.py solve --rooms rooms.json --solver tree --output layout.json
    python solver_cli.py compare --rooms rooms.json --output comparison.html
    python solver_cli.py list
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any

from room_relationships import SpatialGraph, RoomNode, Zone
from complete_solver_suite import CompleteSolverSuite, SolverType, SOLVER_INFO
from visual_comparison import TeachingComparator


def load_rooms_from_json(filepath: str) -> SpatialGraph:
    """Load room definitions from JSON file."""
    data = json.loads(Path(filepath).read_text())

    graph = SpatialGraph()

    for room_data in data.get("rooms", []):
        room_id = room_data["id"]
        room_type = room_data.get("type", "room")
        min_area = room_data.get("min_area", 10.0)

        kwargs = {
            "target_area": room_data.get("target_area", min_area * 1.2),
            "min_width": room_data.get("min_width", 2.5),
            "min_depth": room_data.get("min_depth", 2.5),
            "floor": room_data.get("floor", 0),
        }

        if "zone" in room_data:
            kwargs["zone"] = Zone(room_data["zone"])

        graph.add_room(room_id, room_type, min_area, **kwargs)

    # Load adjacencies
    for adj in data.get("adjacencies", []):
        weight = adj.get("weight", 1.0)
        graph.connect(adj["room_a"], adj["room_b"], weight)

    return graph


def save_layout_to_json(layout, filepath: str):
    """Save layout to JSON file."""
    output = {
        "rooms": {},
        "metadata": {
            "score": layout.score,
            "is_complete": layout.is_complete,
            "iterations": layout.iterations,
            "solve_time_ms": layout.solve_time_ms,
        }
    }

    for room_id, placed in layout.rooms.items():
        output["rooms"][room_id] = {
            "id": room_id,
            "x": placed.rect.x,
            "y": 0,
            "z": placed.rect.y,
            "width": placed.rect.width,
            "depth": placed.rect.height,
            "height": 2.7,  # Default ceiling height
            "area": placed.area,
        }

    Path(filepath).write_text(json.dumps(output, indent=2))


def cmd_list(args):
    """List available solvers."""
    print("\nAvailable Solvers:")
    print("=" * 60)

    for solver_type in SolverType:
        info = SOLVER_INFO.get(solver_type)
        if not info:
            continue

        print(f"\n{solver_type.value}")
        print(f"  Name: {info.name}")
        print(f"  Description: {info.description}")
        print(f"  Speed: {info.speed} | Reliability: {info.reliability}")
        print(f"  Best for: {', '.join(info.best_for)}")


def cmd_solve(args):
    """Run a solver to generate layout."""
    # Load rooms
    print(f"Loading rooms from {args.rooms}...")
    graph = load_rooms_from_json(args.rooms)
    print(f"Loaded {len(graph.rooms)} rooms")

    # Validate
    errors = graph.validate()
    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"  - {err}")
        return 1

    # Parse solver type
    try:
        solver_type = SolverType(args.solver.lower())
    except ValueError:
        print(f"Unknown solver: {args.solver}")
        print(f"Available: {', '.join(st.value for st in SolverType)}")
        return 1

    # Run solver
    print(f"\nRunning {solver_type.value} solver...")
    suite = CompleteSolverSuite(graph, args.width, args.depth, args.grid_size)
    layout = suite.solve(solver_type, max_iterations=args.max_iterations)

    print(f"\nResults:")
    print(f"  Rooms placed: {len(layout.rooms)}/{len(graph.rooms)}")
    print(f"  Score: {layout.score:.2f}")
    print(f"  Iterations: {layout.iterations}")
    print(f"  Time: {layout.solve_time_ms:.1f}ms")
    print(f"  Overlaps: {len(layout.get_overlaps())}")

    # Save output
    save_layout_to_json(layout, args.output)
    print(f"\nLayout saved to {args.output}")

    return 0


def cmd_compare(args):
    """Run all solvers and generate comparison."""
    # Load rooms
    print(f"Loading rooms from {args.rooms}...")
    graph = load_rooms_from_json(args.rooms)
    print(f"Loaded {len(graph.rooms)} rooms")

    # Run all solvers
    print("\nRunning all solvers...")
    suite = CompleteSolverSuite(graph, args.width, args.depth, args.grid_size)
    results = suite.solve_all(max_iterations=args.max_iterations)

    # Print results
    print("\nResults:")
    print("-" * 60)
    print(f"{'Solver':<25} {'Score':>8} {'Rooms':>8} {'Time (ms)':>12}")
    print("-" * 60)

    for solver_type, layout in sorted(results.items(), key=lambda x: -x[1].score):
        info = SOLVER_INFO.get(solver_type)
        name = info.name if info else solver_type.value
        print(f"{name:<25} {layout.score:>8.2f} {len(layout.rooms):>8} {layout.solve_time_ms:>12.1f}")

    # Generate comparison
    if args.output:
        print(f"\nGenerating comparison to {args.output}...")
        comparator = TeachingComparator()
        path = comparator.export_comparison(results, args.width, args.depth, "comparison")
        print(f"Comparison saved to {path}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="ArchEngine Room Layout Solvers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available solvers
  python solver_cli.py list

  # Generate layout with tree solver
  python solver_cli.py solve --rooms rooms.json --solver tree --output layout.json

  # Compare all solvers
  python solver_cli.py compare --rooms rooms.json --output comparison.html
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    list_parser = subparsers.add_parser("list", help="List available solvers")
    list_parser.set_defaults(func=cmd_list)

    # Solve command
    solve_parser = subparsers.add_parser("solve", help="Generate layout with a solver")
    solve_parser.add_argument("--rooms", required=True, help="JSON file with room definitions")
    solve_parser.add_argument("--solver", required=True, help="Solver algorithm to use")
    solve_parser.add_argument("--output", default="layout.json", help="Output file")
    solve_parser.add_argument("--width", type=float, default=15.0, help="Building width (meters)")
    solve_parser.add_argument("--depth", type=float, default=12.0, help="Building depth (meters)")
    solve_parser.add_argument("--grid-size", type=float, default=0.5, help="Grid snap size")
    solve_parser.add_argument("--max-iterations", type=int, default=10000, help="Max iterations")
    solve_parser.set_defaults(func=cmd_solve)

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare all solvers")
    compare_parser.add_argument("--rooms", required=True, help="JSON file with room definitions")
    compare_parser.add_argument("--output", help="Output HTML file for comparison")
    compare_parser.add_argument("--width", type=float, default=15.0, help="Building width (meters)")
    compare_parser.add_argument("--depth", type=float, default=12.0, help="Building depth (meters)")
    compare_parser.add_argument("--grid-size", type=float, default=0.5, help="Grid snap size")
    compare_parser.add_argument("--max-iterations", type=int, default=5000, help="Max iterations")
    compare_parser.set_defaults(func=cmd_compare)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
