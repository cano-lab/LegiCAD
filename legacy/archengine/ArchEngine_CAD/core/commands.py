"""
Undo/Redo Commands for ArchEngine CAD.

Uses Qt's QUndoCommand pattern for fine-grained undo/redo.
"""
from typing import Any, Dict, Tuple, Optional
from PyQt6.QtGui import QUndoCommand


class ModifyWallCommand(QUndoCommand):
    """Command for modifying wall properties."""

    def __init__(self, document, wall_index: int, old_values: Dict, new_values: Dict):
        super().__init__(f"Modify Wall {wall_index}")
        self.document = document
        self.wall_index = wall_index
        self.old_values = old_values
        self.new_values = new_values
        self._first_redo = True

    def redo(self):
        """Apply the modification."""
        # Skip first redo since the action was already performed
        if self._first_redo:
            self._first_redo = False
            return

        wall = self.document._walls[self.wall_index]
        for key, value in self.new_values.items():
            setattr(wall, key, value)

        self.document.set_modified(True)
        self.document.element_modified.emit('wall', str(self.wall_index))
        from core.events import event_bus
        event_bus.element_modified.emit('wall', str(self.wall_index), self.new_values)

    def undo(self):
        """Revert the modification."""
        wall = self.document._walls[self.wall_index]
        for key, value in self.old_values.items():
            setattr(wall, key, value)

        self.document.set_modified(True)
        self.document.element_modified.emit('wall', str(self.wall_index))
        from core.events import event_bus
        event_bus.element_modified.emit('wall', str(self.wall_index), self.old_values)


class AddWallCommand(QUndoCommand):
    """Command for adding a new wall."""

    def __init__(self, document, wall_data: Dict):
        super().__init__("Add Wall")
        self.document = document
        self.wall_data = wall_data
        self.wall_index = -1

    def redo(self):
        """Add the wall."""
        from core.document import Wall

        # Create wall object
        self.wall_index = len(self.document._walls)
        wall = Wall(
            index=self.wall_index,
            start=tuple(self.wall_data.get('start', [0, 0, 0])),
            end=tuple(self.wall_data.get('end', [0, 0, 0])),
            height=self.wall_data.get('height', 2700),
            category=self.wall_data.get('category', 'interior'),
            wall_type=self.wall_data.get('wall_type', '')
        )
        self.document._walls.append(wall)

        self.document.set_modified(True)
        self.document.element_added.emit('wall', str(self.wall_index))
        self.document.document_changed.emit()

    def undo(self):
        """Remove the wall."""
        if self.wall_index >= 0 and self.wall_index < len(self.document._walls):
            self.document._walls.pop(self.wall_index)
            self.document.set_modified(True)
            self.document.element_removed.emit('wall', str(self.wall_index))
            self.document.document_changed.emit()


class DeleteWallCommand(QUndoCommand):
    """Command for deleting a wall."""

    def __init__(self, document, wall_index: int):
        super().__init__(f"Delete Wall {wall_index}")
        self.document = document
        self.wall_index = wall_index
        # Store the wall data for undo
        wall = document._walls[wall_index]
        self.wall_data = {
            'start': wall.start,
            'end': wall.end,
            'height': wall.height,
            'category': wall.category,
            'wall_type': wall.wall_type
        }

    def redo(self):
        """Delete the wall."""
        if self.wall_index < len(self.document._walls):
            self.document._walls.pop(self.wall_index)
            # Update indices of remaining walls
            for i, wall in enumerate(self.document._walls):
                wall.index = i
            self.document.set_modified(True)
            self.document.element_removed.emit('wall', str(self.wall_index))
            self.document.document_changed.emit()

    def undo(self):
        """Restore the wall."""
        from core.document import Wall

        wall = Wall(
            index=self.wall_index,
            start=self.wall_data['start'],
            end=self.wall_data['end'],
            height=self.wall_data['height'],
            category=self.wall_data['category'],
            wall_type=self.wall_data['wall_type']
        )
        self.document._walls.insert(self.wall_index, wall)
        # Update indices
        for i, w in enumerate(self.document._walls):
            w.index = i
        self.document.set_modified(True)
        self.document.element_added.emit('wall', str(self.wall_index))
        self.document.document_changed.emit()


class ModifyDoorCommand(QUndoCommand):
    """Command for modifying door properties."""

    def __init__(self, document, door_index: int, old_values: Dict, new_values: Dict):
        super().__init__(f"Modify Door {door_index}")
        self.document = document
        self.door_index = door_index
        self.old_values = old_values
        self.new_values = new_values
        self._first_redo = True

    def redo(self):
        if self._first_redo:
            self._first_redo = False
            return

        door = self.document._doors[self.door_index]
        for key, value in self.new_values.items():
            setattr(door, key, value)
        self.document.set_modified(True)
        self.document.element_modified.emit('door', str(self.door_index))

    def undo(self):
        door = self.document._doors[self.door_index]
        for key, value in self.old_values.items():
            setattr(door, key, value)
        self.document.set_modified(True)
        self.document.element_modified.emit('door', str(self.door_index))


class ModifyWindowCommand(QUndoCommand):
    """Command for modifying window properties."""

    def __init__(self, document, window_index: int, old_values: Dict, new_values: Dict):
        super().__init__(f"Modify Window {window_index}")
        self.document = document
        self.window_index = window_index
        self.old_values = old_values
        self.new_values = new_values
        self._first_redo = True

    def redo(self):
        if self._first_redo:
            self._first_redo = False
            return

        window = self.document._windows[self.window_index]
        for key, value in self.new_values.items():
            setattr(window, key, value)
        self.document.set_modified(True)
        self.document.element_modified.emit('window', str(self.window_index))

    def undo(self):
        window = self.document._windows[self.window_index]
        for key, value in self.old_values.items():
            setattr(window, key, value)
        self.document.set_modified(True)
        self.document.element_modified.emit('window', str(self.window_index))


class AddDoorCommand(QUndoCommand):
    """Command for adding a new door."""

    def __init__(self, document, door_data: Dict):
        super().__init__("Add Door")
        self.document = document
        self.door_data = door_data
        self.door_index = -1

    def redo(self):
        """Add the door."""
        from core.document import Door

        self.door_index = len(self.document._doors)
        door = Door(
            index=self.door_index,
            wall_index=self.door_data.get('wall_index', 0),
            offset=self.door_data.get('offset', 0),
            width=self.door_data.get('width', 914),
            height=self.door_data.get('height', 2134),
            door_type=self.door_data.get('type', 'swing'),
            swing=self.door_data.get('swing', 'left_in')
        )
        self.document._doors.append(door)

        self.document.set_modified(True)
        self.document.element_added.emit('door', str(self.door_index))
        self.document.document_changed.emit()

    def undo(self):
        """Remove the door."""
        if self.door_index >= 0 and self.door_index < len(self.document._doors):
            self.document._doors.pop(self.door_index)
            # Update indices
            for i, door in enumerate(self.document._doors):
                door.index = i
            self.document.set_modified(True)
            self.document.element_removed.emit('door', str(self.door_index))
            self.document.document_changed.emit()


class AddWindowCommand(QUndoCommand):
    """Command for adding a new window."""

    def __init__(self, document, window_data: Dict):
        super().__init__("Add Window")
        self.document = document
        self.window_data = window_data
        self.window_index = -1

    def redo(self):
        """Add the window."""
        from core.document import Window

        self.window_index = len(self.document._windows)
        window = Window(
            index=self.window_index,
            wall_index=self.window_data.get('wall_index', 0),
            offset=self.window_data.get('offset', 0),
            width=self.window_data.get('width', 1200),
            height=self.window_data.get('height', 1200),
            sill_height=self.window_data.get('sill_height', 900)
        )
        self.document._windows.append(window)

        self.document.set_modified(True)
        self.document.element_added.emit('window', str(self.window_index))
        self.document.document_changed.emit()

    def undo(self):
        """Remove the window."""
        if self.window_index >= 0 and self.window_index < len(self.document._windows):
            self.document._windows.pop(self.window_index)
            # Update indices
            for i, window in enumerate(self.document._windows):
                window.index = i
            self.document.set_modified(True)
            self.document.element_removed.emit('window', str(self.window_index))
            self.document.document_changed.emit()


class MoveWallCommand(QUndoCommand):
    """
    Specialized command for moving walls via grip drag.
    Merges consecutive moves into a single undo action.
    """

    def __init__(self, document, wall_index: int, grip_type: str,
                 old_start: Tuple, old_end: Tuple,
                 new_start: Tuple, new_end: Tuple):
        super().__init__(f"Move Wall {wall_index}")
        self.document = document
        self.wall_index = wall_index
        self.grip_type = grip_type
        self.old_start = old_start
        self.old_end = old_end
        self.new_start = new_start
        self.new_end = new_end
        self._first_redo = True

    def id(self) -> int:
        """Return command ID for merging consecutive moves."""
        return 1001  # Unique ID for wall move commands

    def mergeWith(self, other: QUndoCommand) -> bool:
        """Merge with another move command on the same wall."""
        if not isinstance(other, MoveWallCommand):
            return False
        if other.wall_index != self.wall_index:
            return False
        # Keep our old values, take their new values
        self.new_start = other.new_start
        self.new_end = other.new_end
        return True

    def redo(self):
        if self._first_redo:
            self._first_redo = False
            return

        wall = self.document._walls[self.wall_index]
        wall.start = self.new_start
        wall.end = self.new_end
        self.document.set_modified(True)
        self.document.element_modified.emit('wall', str(self.wall_index))
        from core.events import event_bus
        event_bus.element_modified.emit('wall', str(self.wall_index),
                                        {'start': self.new_start, 'end': self.new_end})

    def undo(self):
        wall = self.document._walls[self.wall_index]
        wall.start = self.old_start
        wall.end = self.old_end
        self.document.set_modified(True)
        self.document.element_modified.emit('wall', str(self.wall_index))
        from core.events import event_bus
        event_bus.element_modified.emit('wall', str(self.wall_index),
                                        {'start': self.old_start, 'end': self.old_end})


class AddRoomCommand(QUndoCommand):
    """Command for adding a new room."""

    def __init__(self, document, room_data: Dict):
        super().__init__("Add Room")
        self.document = document
        self.room_data = room_data
        self.room_id = None

    def redo(self):
        """Add the room."""
        from core.document import Room
        import uuid

        # Generate unique ID if not provided
        self.room_id = self.room_data.get('id', str(uuid.uuid4())[:8])

        # Calculate bounding box from vertices
        vertices = self.room_data.get('vertices', [])
        if vertices:
            xs = [v[0] for v in vertices]
            zs = [v[1] for v in vertices]
            bounds = {
                'x': min(xs),
                'y': min(zs),
                'width': max(xs) - min(xs),
                'height': max(zs) - min(zs)
            }
            center = {
                'x': (min(xs) + max(xs)) / 2,
                'z': (min(zs) + max(zs)) / 2
            }
        else:
            bounds = self.room_data.get('bounds', {'x': 0, 'y': 0, 'width': 0, 'height': 0})
            center = self.room_data.get('center')

        room = Room(
            id=self.room_id,
            name=self.room_data.get('name', f'Room {len(self.document._rooms) + 1}'),
            room_type=self.room_data.get('room_type', 'generic'),
            bounds=bounds,
            area=self.room_data.get('area', 0),
            center=center,
            vertices=vertices,
            index=len(self.document._rooms)
        )
        self.document._rooms[self.room_id] = room

        self.document.set_modified(True)
        self.document.element_added.emit('room', self.room_id)
        self.document.document_changed.emit()

    def undo(self):
        """Remove the room."""
        if self.room_id and self.room_id in self.document._rooms:
            del self.document._rooms[self.room_id]
            self.document.set_modified(True)
            self.document.element_removed.emit('room', self.room_id)
            self.document.document_changed.emit()


class DeleteDoorCommand(QUndoCommand):
    """Command for deleting a door."""

    def __init__(self, document, door_index: int):
        super().__init__(f"Delete Door {door_index}")
        self.document = document
        self.door_index = door_index
        # Store the door data for undo
        door = document._doors[door_index]
        self.door_data = {
            'wall_index': door.wall_index,
            'offset': door.offset,
            'width': door.width,
            'height': door.height,
            'door_type': door.door_type,
            'swing': door.swing
        }

    def redo(self):
        """Delete the door."""
        if self.door_index < len(self.document._doors):
            self.document._doors.pop(self.door_index)
            # Update indices of remaining doors
            for i, door in enumerate(self.document._doors):
                door.index = i
            self.document.set_modified(True)
            self.document.element_removed.emit('door', str(self.door_index))
            self.document.document_changed.emit()

    def undo(self):
        """Restore the door."""
        from core.document import Door

        door = Door(
            index=self.door_index,
            wall_index=self.door_data['wall_index'],
            offset=self.door_data['offset'],
            width=self.door_data['width'],
            height=self.door_data['height'],
            door_type=self.door_data['door_type'],
            swing=self.door_data['swing']
        )
        self.document._doors.insert(self.door_index, door)
        # Update indices
        for i, d in enumerate(self.document._doors):
            d.index = i
        self.document.set_modified(True)
        self.document.element_added.emit('door', str(self.door_index))
        self.document.document_changed.emit()


class DeleteWindowCommand(QUndoCommand):
    """Command for deleting a window."""

    def __init__(self, document, window_index: int):
        super().__init__(f"Delete Window {window_index}")
        self.document = document
        self.window_index = window_index
        # Store the window data for undo
        window = document._windows[window_index]
        self.window_data = {
            'wall_index': window.wall_index,
            'offset': window.offset,
            'width': window.width,
            'height': window.height,
            'sill_height': window.sill_height
        }

    def redo(self):
        """Delete the window."""
        if self.window_index < len(self.document._windows):
            self.document._windows.pop(self.window_index)
            # Update indices of remaining windows
            for i, window in enumerate(self.document._windows):
                window.index = i
            self.document.set_modified(True)
            self.document.element_removed.emit('window', str(self.window_index))
            self.document.document_changed.emit()

    def undo(self):
        """Restore the window."""
        from core.document import Window

        window = Window(
            index=self.window_index,
            wall_index=self.window_data['wall_index'],
            offset=self.window_data['offset'],
            width=self.window_data['width'],
            height=self.window_data['height'],
            sill_height=self.window_data['sill_height']
        )
        self.document._windows.insert(self.window_index, window)
        # Update indices
        for i, w in enumerate(self.document._windows):
            w.index = i
        self.document.set_modified(True)
        self.document.element_added.emit('window', str(self.window_index))
        self.document.document_changed.emit()


class DeleteRoomCommand(QUndoCommand):
    """Command for deleting a room."""

    def __init__(self, document, room_id: str):
        super().__init__(f"Delete Room {room_id}")
        self.document = document
        self.room_id = room_id
        # Store the room data for undo
        room = document._rooms[room_id]
        self.room_data = {
            'id': room.id,
            'name': room.name,
            'room_type': room.room_type,
            'bounds': room.bounds,
            'area': room.area,
            'center': room.center,
            'vertices': room.vertices,
            'index': room.index
        }

    def redo(self):
        """Delete the room."""
        if self.room_id in self.document._rooms:
            del self.document._rooms[self.room_id]
            self.document.set_modified(True)
            self.document.element_removed.emit('room', self.room_id)
            self.document.document_changed.emit()

    def undo(self):
        """Restore the room."""
        from core.document import Room

        room = Room(
            id=self.room_data['id'],
            name=self.room_data['name'],
            room_type=self.room_data['room_type'],
            bounds=self.room_data['bounds'],
            area=self.room_data['area'],
            center=self.room_data['center'],
            vertices=self.room_data['vertices'],
            index=self.room_data['index']
        )
        self.document._rooms[self.room_id] = room
        self.document.set_modified(True)
        self.document.element_added.emit('room', self.room_id)
        self.document.document_changed.emit()
