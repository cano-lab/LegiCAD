"""Test script for LegiQBD conversational flow."""

import sys
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import LLMConfig
from legiqbd import ConversationEngine, Session, quick_preview, render_rooms


def test_flow():
    """Test the full conversational flow."""
    print("=" * 60)
    print("LegiQBD Flow Test")
    print("=" * 60)

    # Check LLM
    status = LLMConfig.status()
    print(f"\nLLM Status: {status.get('active', 'none')}")

    if not status.get("active"):
        print("ERROR: No LLM provider available")
        return False

    # Create engine
    print("\n1. Creating engine...")
    engine = ConversationEngine()

    # Start conversation
    print("\n2. Starting conversation...")
    response = engine.start_conversation()
    print(f"   Greeting: {response.text[:100]}...")

    # Send initial description
    print("\n3. Describing building...")
    response = engine.process_input(
        "I want a 3 bedroom 2 bathroom house with an open kitchen and living room, "
        "about 1800 square feet, single story"
    )

    print(f"   Response: {response.text[:150]}...")
    print(f"   Fragments applied: {len(response.fragments_applied)}")
    print(f"   Errors: {response.errors}")
    print(f"   Design changed: {response.design_changed}")
    print(f"   Is solvable: {response.is_solvable}")

    # Show rooms
    rooms = engine.session.qbd_state.rooms
    print(f"\n4. Rooms created: {len(rooms)}")
    print(quick_preview(rooms))

    # Try to solve
    print("\n5. Attempting solve...")
    if engine.session.is_solvable:
        success, result = engine.solve()
        if success:
            print(f"   SOLVED! Score: {result.get('score', 0):.1f}/10")

            layout = result.get("layout", {})
            if layout.get("rooms"):
                print(f"   Footprint: {layout.get('metrics', {}).get('footprint_width', 0):.1f}m x {layout.get('metrics', {}).get('footprint_depth', 0):.1f}m")
        else:
            print(f"   Failed: {result.get('error')}")
    else:
        print("   Not ready to solve - need more info")

        # Add constraint to make solvable
        print("\n5b. Adding footprint constraint...")
        from qbd import set_constraint
        engine.session.qbd_state.apply_fragment(set_constraint("footprint_max", 180))

        if engine.session.is_solvable:
            success, result = engine.solve()
            if success:
                print(f"   SOLVED! Score: {result.get('score', 0):.1f}/10")

    # Try modification
    print("\n6. Modifying design...")
    response = engine.process_input("Make the kitchen bigger and add a home office")

    print(f"   Response: {response.text[:150]}...")
    print(f"   Fragments applied: {len(response.fragments_applied)}")
    print(f"   Design changed: {response.design_changed}")

    # Show updated rooms
    rooms = engine.session.qbd_state.rooms
    print(f"\n7. Updated rooms: {len(rooms)}")
    print(quick_preview(rooms))

    # Final status
    print("\n8. Final status:")
    summary = engine.session.get_state_summary()
    print(f"   Phase: {summary['phase']}")
    print(f"   Rooms: {summary['rooms']['count']}")
    print(f"   Solved: {summary['is_solved']}")
    print(f"   Solve count: {summary['solve_count']}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = test_flow()
    sys.exit(0 if success else 1)
