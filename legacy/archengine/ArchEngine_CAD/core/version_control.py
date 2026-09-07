"""
Git-based version control for JSON building files.

Uses git to track changes, allowing:
- Automatic commits on save
- Diff viewing before save
- Revert to previous versions
- Change history
"""
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime


class VersionControl:
    """
    Git-based version control for a single file.
    Creates a .history folder alongside the file with git tracking.
    """

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.history_dir = self.file_path.parent / '.history'
        self.tracked_file = self.history_dir / self.file_path.name
        self._git_available = self._check_git()

    def _check_git(self) -> bool:
        """Check if git is available."""
        try:
            result = subprocess.run(
                ['git', '--version'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            return result.returncode == 0
        except (FileNotFoundError, OSError):
            return False

    def _run_git(self, *args, cwd: Optional[Path] = None) -> Tuple[bool, str]:
        """Run a git command in the history directory."""
        if not self._git_available:
            return False, "Git not available"

        try:
            result = subprocess.run(
                ['git'] + list(args),
                cwd=cwd or self.history_dir,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def init(self) -> bool:
        """Initialize version control for the file."""
        if not self._git_available:
            print("Git not available - version control disabled")
            return False

        # Create history directory
        self.history_dir.mkdir(exist_ok=True)

        # Initialize git repo if not exists
        git_dir = self.history_dir / '.git'
        if not git_dir.exists():
            success, output = self._run_git('init')
            if not success:
                print(f"Failed to init git: {output}")
                return False

            # Configure git for this repo
            self._run_git('config', 'user.email', 'archengine@local')
            self._run_git('config', 'user.name', 'ArchEngine CAD')

        # Copy current file to history if it exists
        if self.file_path.exists():
            shutil.copy2(self.file_path, self.tracked_file)
            self._run_git('add', self.file_path.name)
            self._run_git('commit', '-m', 'Initial version')

        return True

    def get_diff(self, new_content: str) -> Optional[str]:
        """
        Get diff between current tracked version and new content.
        Returns None if no changes or git unavailable.
        """
        if not self._git_available or not self.tracked_file.exists():
            return None

        # Write new content to temp file
        temp_file = self.history_dir / f'{self.file_path.name}.new'
        try:
            temp_file.write_text(new_content, encoding='utf-8')

            # Get diff
            success, output = self._run_git(
                'diff', '--no-color', self.file_path.name, f'{self.file_path.name}.new'
            )

            return output if output.strip() else None
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def commit(self, content: str, message: Optional[str] = None) -> bool:
        """
        Commit new version of the file.

        Args:
            content: New file content
            message: Commit message (auto-generated if None)
        """
        if not self._git_available:
            return False

        # Ensure history dir exists
        if not self.history_dir.exists():
            self.init()

        # Write content to tracked file
        self.tracked_file.write_text(content, encoding='utf-8')

        # Stage the file
        self._run_git('add', self.file_path.name)

        # Check if there are changes to commit
        success, status = self._run_git('status', '--porcelain')
        if not status.strip():
            return True  # No changes to commit

        # Generate commit message
        if not message:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            message = f'Save at {timestamp}'

        # Commit
        success, output = self._run_git('commit', '-m', message)
        return success

    def get_history(self, limit: int = 20) -> List[Dict]:
        """
        Get commit history.

        Returns list of dicts with: hash, date, message
        """
        if not self._git_available or not (self.history_dir / '.git').exists():
            return []

        success, output = self._run_git(
            'log', f'-{limit}', '--pretty=format:%H|%ai|%s', '--', self.file_path.name
        )

        if not success or not output.strip():
            return []

        history = []
        for line in output.strip().split('\n'):
            parts = line.split('|', 2)
            if len(parts) == 3:
                history.append({
                    'hash': parts[0],
                    'date': parts[1],
                    'message': parts[2]
                })

        return history

    def get_version(self, commit_hash: str) -> Optional[str]:
        """Get file content at a specific commit."""
        if not self._git_available:
            return None

        success, output = self._run_git('show', f'{commit_hash}:{self.file_path.name}')
        return output if success else None

    def revert_to(self, commit_hash: str) -> bool:
        """
        Revert file to a specific commit.
        Creates a new commit with the reverted content.
        """
        content = self.get_version(commit_hash)
        if content is None:
            return False

        # Write to original file
        self.file_path.write_text(content, encoding='utf-8')

        # Commit the revert
        return self.commit(content, f'Reverted to {commit_hash[:8]}')

    def get_changes_summary(self, new_content: str) -> Optional[Dict]:
        """
        Get a summary of changes between tracked and new content.

        Returns dict with:
        - walls_changed: number of walls modified
        - doors_changed: number of doors modified
        - windows_changed: number of windows modified
        """
        import json

        if not self.tracked_file.exists():
            return None

        try:
            old_data = json.loads(self.tracked_file.read_text(encoding='utf-8'))
            new_data = json.loads(new_content)
        except json.JSONDecodeError:
            return None

        summary = {
            'walls_added': 0,
            'walls_removed': 0,
            'walls_modified': 0,
            'doors_changed': 0,
            'windows_changed': 0,
        }

        # Compare walls
        old_walls = old_data.get('walls_batch', [])
        new_walls = new_data.get('walls_batch', [])

        summary['walls_added'] = max(0, len(new_walls) - len(old_walls))
        summary['walls_removed'] = max(0, len(old_walls) - len(new_walls))

        # Check for modifications in existing walls
        for i in range(min(len(old_walls), len(new_walls))):
            if old_walls[i] != new_walls[i]:
                summary['walls_modified'] += 1

        # Compare doors
        old_doors = old_data.get('doors', [])
        new_doors = new_data.get('doors', [])
        if old_doors != new_doors:
            summary['doors_changed'] = abs(len(new_doors) - len(old_doors))
            for i in range(min(len(old_doors), len(new_doors))):
                if old_doors[i] != new_doors[i]:
                    summary['doors_changed'] += 1

        # Compare windows
        old_windows = old_data.get('windows', [])
        new_windows = new_data.get('windows', [])
        if old_windows != new_windows:
            summary['windows_changed'] = abs(len(new_windows) - len(old_windows))
            for i in range(min(len(old_windows), len(new_windows))):
                if old_windows[i] != new_windows[i]:
                    summary['windows_changed'] += 1

        return summary


# Convenience function
def create_version_control(file_path: Path) -> Optional[VersionControl]:
    """Create and initialize version control for a file."""
    vc = VersionControl(file_path)
    if vc.init():
        return vc
    return None
