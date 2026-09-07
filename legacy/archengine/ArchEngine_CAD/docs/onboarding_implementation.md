# Onboarding UX Implementation

## Overview

A new onboarding experience that shows a centered, prominent chat interface for the first 3 questions, then smoothly animates to the normal side-panel layout.

**Key Feature:** Onboarding is **per-document**, not per-user. Each file remembers whether it has completed onboarding.

## Features

### 1. Onboarding Overlay (`onboarding_overlay.py`)

**Class: `OnboardingOverlay`**

- Full-screen overlay with semi-transparent dark background
- Centered chat panel (600px wide, min 500px tall)
- Progress indicator ("Question X of 3")
- Animated progress bar
- Dynamic subtitle that updates as questions are answered

**Animations:**
- **Fade in**: 500ms fade-in on show
- **Progress bar**: 300ms smooth updates
- **Transition**: 1000ms slide + 800ms fade-out sequence

### 2. Document Integration (`document.py`)

**New Properties and Methods:**

```python
@property
def onboarding_completed(self) -> bool:
    """Check if this document has completed the onboarding flow."""
    return self._data.get('onboarding_completed', False)

def complete_onboarding(self):
    """Mark onboarding as completed for this document."""
    self._data['onboarding_completed'] = True
    self._modified = True

def reset_onboarding(self):
    """Reset onboarding for this document."""
    self._data['onboarding_completed'] = False
    self._modified = True
```

**Document Schema:**
```json
{
  "building_id": "...",
  "walls_batch": [],
  "onboarding_completed": false,  // ← Saved with document!
  ...
}
```

### 3. Application Integration (`application.py`)

**Key Behavior Changes:**

- **New files**: Always show onboarding (onboarding_completed defaults to `false`)
- **Existing files**: Show onboarding only if `onboarding_completed` is `false`
- **After completion**: Flag is saved to document (requires saving to persist)

**Methods:**

- `_show_onboarding_if_needed()`: Checks document.onboarding_completed and shows overlay if needed
- `_on_onboarding_complete()`: Marks document as complete, shows normal UI
- `_on_reset_onboarding()`: Resets onboarding for current document

**Trigger Points:**

1. Application starts with new document → shows onboarding
2. File → New → shows onboarding
3. File → Open → shows onboarding if file hasn't completed it
4. File → Save → persists onboarding completion flag

## User Flow

### New Document

```
1. Launch App → Creates new document → Shows onboarding
2. User answers 3 questions
3. Onboarding completes, shows normal workspace
4. User saves file → onboarding flag saved to JSON
```

### Existing Document (Completed Onboarding)

```
1. File → Open → Opens file
2. Checks onboarding_completed == true
3. Skips onboarding, shows normal workspace
```

### Existing Document (Not Completed)

```
1. File → Open → Opens file
2. Checks onboarding_completed == false
3. Shows onboarding
4. User completes or skips
5. User saves to persist
```

## Testing

### Test 1: New Document Shows Onboarding

1. Clear QSettings to remove last_project:
   ```python
   from PyQt6.QtCore import QSettings
   settings = QSettings("ArchEngine", "CAD")
   settings.remove("last_project")
   ```

2. Launch application
3. Should see centered welcome screen
4. Document's `onboarding_completed` should be `false`

### Test 2: Onboarding Completes Per Document

1. Complete 3 questions in chat
2. After animation, check:
   ```python
   app.document.onboarding_completed  # Should be True
   app.document.modified  # Should be True
   ```

3. Save file
4. Close and reopen
5. Should NOT see onboarding (document completed)

### Test 3: Multiple Files, Different States

1. File A: Complete onboarding, save
2. File B: Skip onboarding, save
3. File C: New document

**Expected:**
- Opening File A: No onboarding
- Opening File B: Shows onboarding
- File C (new): Shows onboarding

### Test 4: Reset Onboarding

1. Open any file
2. View → Reset Onboarding...
3. Confirm dialog
4. Onboarding shows again for that file
5. Save to persist the reset

## JSON Structure

### Before Onboarding
```json
{
  "building_id": "new_building",
  "width": 10000,
  "depth": 10000,
  "walls_batch": [],
  "onboarding_completed": false
}
```

### After Onboarding
```json
{
  "building_id": "new_building",
  "width": 10000,
  "depth": 10000,
  "walls_batch": [],
  "onboarding_completed": true,  // ← Flag updated
  "rooms": {...},  // User's design
  ...
}
```

## Customization

### Change Number of Questions

Edit `onboarding_overlay.py`:
```python
def __init__(self, chat_panel, parent=None):
    super().__init__(parent)
    self.chat_panel = chat_panel
    self.question_count = 0
    self.max_questions = 5  # Change from 3 to any number
```

### Adjust Animation Timing

Edit `onboarding_overlay.py`:
```python
# Fade in timing
fade_in.setDuration(500)  # milliseconds

# Progress bar timing
self.progress_anim.setDuration(300)

# Transition timing
self.chat_slide.setDuration(1000)  # slide duration
self.fade_out.setDuration(800)     # fade duration
```

### Change Overlay Styling

Edit `onboarding_overlay.py` `_setup_ui()` method:
```python
# Background color
self.background.setStyleSheet("""
    QFrame {
        background-color: rgba(30, 30, 35, 0.95);  # Adjust opacity
    }
""")

# Chat container
self.chat_container.setStyleSheet("""
    QFrame {
        background-color: rgba(45, 45, 50, 0.98);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
    }
""")
```

## Files Modified

### Core Changes

1. **`core/document.py`**
   - Added `onboarding_completed` property
   - Added `complete_onboarding()` method
   - Added `reset_onboarding()` method
   - New documents start with `onboarding_completed: false`

2. **`app/application.py`**
   - Changed from global QSettings to per-document tracking
   - Renamed `_setup_onboarding()` to `_show_onboarding_if_needed()`
   - Calls onboarding check after `new()` and `load()`
   - Updated reset onboarding to work on current document

3. **`main.py`**
   - Creates new document on startup if no file to open
   - Ensures first-launch users see onboarding

### New Files

4. **`panels/onboarding_overlay.py`** (unchanged)
   - OnboardingOverlay class
   - FloatingChatWidget class
   - Animation system

## Troubleshooting

**Onboarding shows for every file:**
- Check that files are being saved after onboarding completes
- Verify `onboarding_completed` is being written to JSON

**Onboarding doesn't show for new files:**
- Check that `document.onboarding_completed` returns `false` for new documents
- Verify `_show_onboarding_if_needed()` is being called after `document.new()`

**Reset onboarding doesn't work:**
- Check that `document.reset_onboarding()` is being called
- Verify `_show_onboarding_if_needed()` is triggered after reset

**Changes lost after closing without saving:**
- Normal behavior! The `onboarding_completed` flag is part of document data
- Must save to persist the flag

## Future Enhancements

Possible improvements:
1. **Skip onboarding button**: For experienced users
2. **Tutorial tooltips**: Point to key UI elements after transition
3. **Welcome video/image**: Instead of just text
4. **Question branching**: Different paths based on answers
5. **Auto-save after onboarding**: Don't lose progress if user forgets to save
6. **Keyboard shortcuts**: Press Enter to submit questions
7. **Question hints**: Show example questions for each step
8. **Per-file templates**: Different onboarding for different project types
