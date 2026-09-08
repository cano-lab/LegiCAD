"""Interactive demo of LegiQBD conversation."""

import sys
import io
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))

from legiqbd import ConversationEngine, quick_preview
from legiqbd.visualizer import ASCIIVisualizer


def run_demo():
    """Run a demo conversation."""
    # Create engine
    engine = ConversationEngine()

    print("=" * 60)
    print("LegiQBD Conversation Demo")
    print("=" * 60)

    # Start conversation
    response = engine.start_conversation()
    print(f"\nLegiQBD: {response.text}")
    print(f"[Phase: {response.phase}]")

    # User describes home
    print("\n" + "-" * 60)
    print("User: I want a 3 bedroom 2 bath ranch house, about 1800 sqft,")
    print("      with an open concept kitchen and living room")
    print("-" * 60)

    response = engine.process_input(
        "I want a 3 bedroom 2 bath ranch house, about 1800 square feet, "
        "with an open concept kitchen and living room"
    )

    print(f"\nLegiQBD: {response.text}")
    print(f"\n[Phase: {response.phase} | Rooms: {engine.session.room_count} | "
          f"Solvable: {response.is_solvable} | Solved: {response.is_solved}]")

    # Show rooms
    print("\n" + quick_preview(engine.session.qbd_state.rooms))

    # User asks to modify
    print("\n" + "-" * 60)
    print("User: Add a home office and make the primary bedroom bigger")
    print("-" * 60)

    response = engine.process_input(
        "Add a home office and make the primary bedroom bigger"
    )

    print(f"\nLegiQBD: {response.text}")
    print(f"\n[Phase: {response.phase} | Rooms: {engine.session.room_count}]")

    # Show updated rooms
    print("\n" + quick_preview(engine.session.qbd_state.rooms))

    # Show layout if solved
    if engine.session.is_solved and engine.session.solved_layout:
        print("\n" + "-" * 60)
        print("FLOOR PLAN:")
        print("-" * 60)
        viz = ASCIIVisualizer(width=55, height=22, use_unicode=False)
        print(viz.render(engine.session.solved_layout))

    # Session summary
    print("\n" + "=" * 60)
    print("Session Summary:")
    summary = engine.session.get_state_summary()
    print(f"  Phase: {summary['phase']}")
    print(f"  Rooms: {summary['rooms']['count']}")
    print(f"  Adjacencies: {summary['adjacencies']}")
    print(f"  Solved: {summary['is_solved']}")
    print(f"  Solve count: {summary['solve_count']}")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
