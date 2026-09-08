"""
Migration script for converting JSON files to database.

Usage:
    python -m database.migrate --input /path/to/project.json --workspace default
    python -m database.migrate --scan-dir /path/to/projects --workspace default
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any

from database.engine import init_db, get_session, DatabaseSession
from database.repository.project import ProjectRepository
from database.models.workspace import Workspace


def migrate_json_file(
    file_path: Path,
    workspace_id: str,
    session=None,
) -> str:
    """
    Migrate a single JSON file to the database.

    Args:
        file_path: Path to JSON file
        workspace_id: Target workspace ID
        session: Optional database session

    Returns:
        Created project ID
    """
    print(f"Migrating: {file_path}")

    # Read JSON file
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Use project name from file or QBD answers
    name = data.get('name')
    if not name:
        qbd = data.get('qbd_answers', {})
        name = qbd.get('description', file_path.stem)

    data['name'] = name

    # Create or use session
    close_session = False
    if session is None:
        session = get_session()
        close_session = True

    try:
        repo = ProjectRepository(session)
        project = repo.import_from_dict(data, workspace_id)
        session.commit()

        print(f"  Created project: {project.id} ({project.name})")
        print(f"  - {len(data.get('walls_batch', []))} walls")
        print(f"  - {len(data.get('doors', []))} doors")
        print(f"  - {len(data.get('windows', []))} windows")
        print(f"  - {len(data.get('rooms', {}))} rooms")

        return project.id

    finally:
        if close_session:
            session.close()


def migrate_directory(
    dir_path: Path,
    workspace_id: str,
    recursive: bool = False,
) -> List[str]:
    """
    Migrate all JSON files in a directory.

    Args:
        dir_path: Directory to scan
        workspace_id: Target workspace ID
        recursive: Scan subdirectories

    Returns:
        List of created project IDs
    """
    pattern = '**/*.json' if recursive else '*.json'
    json_files = list(dir_path.glob(pattern))

    # Filter out non-building files
    json_files = [
        f for f in json_files
        if _is_building_json(f)
    ]

    print(f"Found {len(json_files)} building JSON files")

    project_ids = []

    with DatabaseSession() as session:
        for file_path in json_files:
            try:
                project_id = migrate_json_file(file_path, workspace_id, session)
                project_ids.append(project_id)
            except Exception as e:
                print(f"  ERROR: {e}")

    return project_ids


def _is_building_json(file_path: Path) -> bool:
    """Check if a JSON file looks like a building file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check for typical building file keys
        return any(key in data for key in ['walls_batch', 'walls', 'rooms', 'building_type'])
    except Exception:
        return False


def ensure_workspace(workspace_id: str, name: str = None) -> str:
    """Ensure a workspace exists, create if not."""
    with DatabaseSession() as session:
        workspace = session.query(Workspace).filter(
            Workspace.id == workspace_id
        ).first()

        if not workspace:
            workspace = Workspace(
                id=workspace_id,
                name=name or workspace_id,
            )
            session.add(workspace)
            session.commit()
            print(f"Created workspace: {workspace_id}")

        return workspace.id


def export_to_json(project_id: str, output_path: Path) -> bool:
    """
    Export a project from database to JSON file.

    Args:
        project_id: Project ID to export
        output_path: Output file path

    Returns:
        True if successful
    """
    with DatabaseSession() as session:
        repo = ProjectRepository(session)
        project = repo.get_with_elements(project_id)

        if not project:
            print(f"Project not found: {project_id}")
            return False

        data = repo.export_to_dict(project)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        print(f"Exported to: {output_path}")
        return True


def list_projects(workspace_id: str = None):
    """List all projects in the database."""
    with DatabaseSession() as session:
        query = session.query(
            "id", "name", "building_type", "created_at"
        ).select_from(Workspace)

        from database.models.project import Project

        if workspace_id:
            projects = session.query(Project).filter(
                Project.workspace_id == workspace_id
            ).all()
        else:
            projects = session.query(Project).all()

        print(f"\nProjects ({len(projects)}):")
        print("-" * 60)
        for p in projects:
            print(f"  {p.id[:8]}... | {p.name[:30]:<30} | {p.building_type}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate JSON building files to database"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Import command
    import_parser = subparsers.add_parser("import", help="Import JSON file(s)")
    import_parser.add_argument(
        "--input", "-i",
        type=Path,
        help="Single JSON file to import"
    )
    import_parser.add_argument(
        "--scan-dir", "-d",
        type=Path,
        help="Directory to scan for JSON files"
    )
    import_parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Scan subdirectories"
    )
    import_parser.add_argument(
        "--workspace", "-w",
        default="default",
        help="Target workspace ID"
    )

    # Export command
    export_parser = subparsers.add_parser("export", help="Export project to JSON")
    export_parser.add_argument("project_id", help="Project ID to export")
    export_parser.add_argument("output", type=Path, help="Output file path")

    # List command
    list_parser = subparsers.add_parser("list", help="List projects")
    list_parser.add_argument(
        "--workspace", "-w",
        help="Filter by workspace"
    )

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize database")

    args = parser.parse_args()

    # Initialize database
    init_db()

    if args.command == "import":
        # Ensure workspace exists
        ensure_workspace(args.workspace)

        if args.input:
            migrate_json_file(args.input, args.workspace)
        elif args.scan_dir:
            migrate_directory(args.scan_dir, args.workspace, args.recursive)
        else:
            parser.error("Either --input or --scan-dir required")

    elif args.command == "export":
        export_to_json(args.project_id, args.output)

    elif args.command == "list":
        list_projects(args.workspace)

    elif args.command == "init":
        print("Database initialized successfully")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
