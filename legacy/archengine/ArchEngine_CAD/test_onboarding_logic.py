#!/usr/bin/env python3
"""
Test onboarding flow without GUI.
Validates that new documents show onboarding and existing documents don't.
"""

import sys
from pathlib import Path

# Add CAD directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.document import ArchDocument


def test_new_document_shows_onboarding():
    """Test that new documents have onboarding not completed."""
    print("=" * 70)
    print("TEST 1: New Document Onboarding Status")
    print("=" * 70)

    doc = ArchDocument()
    doc.new()

    print(f"New document created")
    print(f"  onboarding_completed: {doc.onboarding_completed}")
    print(f"  Expected: False")

    assert doc.onboarding_completed == False, "New documents should not have completed onboarding"
    print("  ✓ PASS: New documents show onboarding\n")
    return True


def test_complete_onboarding():
    """Test completing onboarding marks document as done."""
    print("=" * 70)
    print("TEST 2: Complete Onboarding")
    print("=" * 70)

    doc = ArchDocument()
    doc.new()

    print(f"Before complete_onboarding():")
    print(f"  onboarding_completed: {doc.onboarding_completed}")

    doc.complete_onboarding()

    print(f"After complete_onboarding():")
    print(f"  onboarding_completed: {doc.onboarding_completed}")
    print(f"  modified: {doc.modified}")
    print(f"  Expected: True, True")

    assert doc.onboarding_completed == True, "Should be marked complete"
    assert doc.modified == True, "Document should be marked modified"
    print("  ✓ PASS: Onboarding completion works\n")
    return True


def test_reset_onboarding():
    """Test resetting onboarding."""
    print("=" * 70)
    print("TEST 3: Reset Onboarding")
    print("=" * 70)

    doc = ArchDocument()
    doc.new()
    doc.complete_onboarding()

    print(f"Before reset_onboarding():")
    print(f"  onboarding_completed: {doc.onboarding_completed}")

    doc.reset_onboarding()

    print(f"After reset_onboarding():")
    print(f"  onboarding_completed: {doc.onboarding_completed}")
    print(f"  modified: {doc.modified}")
    print(f"  Expected: False, True")

    assert doc.onboarding_completed == False, "Should be reset"
    assert doc.modified == True, "Document should be marked modified"
    print("  ✓ PASS: Onboarding reset works\n")
    return True


def test_document_save_load_with_onboarding():
    """Test that onboarding flag persists through save/load."""
    print("=" * 70)
    print("TEST 4: Onboarding Persists Through Save/Load")
    print("=" * 70)

    import tempfile
    import json

    # Create doc and complete onboarding
    doc1 = ArchDocument()
    doc1.new()
    doc1.complete_onboarding()

    # Save to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)
        json.dump(doc1.to_dict(), f)

    print(f"Saved document with onboarding_completed=True")

    # Load into new document
    doc2 = ArchDocument()
    doc2.load(temp_path)

    print(f"Loaded document:")
    print(f"  onboarding_completed: {doc2.onboarding_completed}")
    print(f"  Expected: True")

    # Clean up
    temp_path.unlink()

    assert doc2.onboarding_completed == True, "Onboarding flag should persist"
    print("  ✓ PASS: Onboarding flag persists\n")
    return True


def test_old_files_without_flag():
    """Test that old files without onboarding flag default to False."""
    print("=" * 70)
    print("TEST 5: Old Files Without Flag Default to False")
    print("=" * 70)

    import tempfile
    import json

    # Create old-style JSON without onboarding flag
    old_data = {
        "building_id": "test",
        "width": 10000,
        "depth": 10000,
        "walls_batch": [],
        "rooms": {}
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)
        json.dump(old_data, f)

    print(f"Created old-style file without onboarding flag")

    # Load into document
    doc = ArchDocument()
    doc.load(temp_path)

    print(f"Loaded document:")
    print(f"  onboarding_completed: {doc.onboarding_completed}")
    print(f"  Expected: False (should show onboarding)")

    # Clean up
    temp_path.unlink()

    assert doc.onboarding_completed == False, "Old files should show onboarding"
    print("  ✓ PASS: Old files default to showing onboarding\n")
    return True


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "ONBOARDING LOGIC TESTS" + " " * 30 + "║")
    print("╚" + "═" * 68 + "╝")
    print("\n")

    tests = [
        test_new_document_shows_onboarding,
        test_complete_onboarding,
        test_reset_onboarding,
        test_document_save_load_with_onboarding,
        test_old_files_without_flag,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"  ✗ FAIL: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            failed += 1

    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed == 0:
        print("\n✓ All tests passed! Onboarding logic is working correctly.")
        print("\nTo test the GUI onboarding:")
        print("1. Run: python main.py")
        print("2. You should see the centered welcome screen")
        print("3. Answer 3 questions in chat")
        print("4. Watch the animated transition")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
