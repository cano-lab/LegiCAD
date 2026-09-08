"""
Archengine Headless API Server

FastAPI-based server providing programmatic access to:
- Building generation (9 spatial solvers)
- Sheet generation (floor plans, elevations, sections)
- PDF export (permit-ready drawings)
- Constraint solving (QBD algebra)
"""

import json
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Import Archengine core
import sys
sys.path.insert(0, '/root/ArchEngine/ArchEngine_kernel/scripts/sheets')
sys.path.insert(0, '/root/ArchEngine/ArchEngine_CAD')
sys.path.insert(0, '/root/ArchEngine/ArchEngine_kernel/qbd')

from interactive_sheet import InteractiveSheet
from sheet_sizes import SheetSize, get_sheet_size
from pdf_export import PDFExportSession, SheetSize as PDFSheetSize

# Import solvers and refiner
try:
    from complete_solver_suite import CompleteSolverSuite, SolverType
    from room_relationships import SpatialGraph
    from coordinate_solver import LayoutSpec
    from layout_refiner import LayoutRefiner, DesignFragment, refine_layout
    SOLVER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Solver integration not available: {e}")
    SOLVER_AVAILABLE = False


# =============================================================================
# DATA MODELS
# =============================================================================

class RoomSpec(BaseModel):
    """Room specification for generation."""
    name: str
    room_type: str  # living, bedroom, kitchen, bathroom, etc.
    min_area_sqm: float = Field(default=0, ge=0)
    preferred_adjacencies: List[str] = []
    required_adjacencies: List[str] = []


class StructureType(str):
    """Types of structures Archengine can generate."""
    RESIDENTIAL = "residential"
    SHED = "shed"
    GARAGE = "garage"
    WORKSHOP = "workshop"
    BARN = "barn"


class BuildingRequest(BaseModel):
    """Request to generate a new building."""
    structure_type: str = Field(default="residential")
    target_area_sqm: float = Field(default=100, gt=0)
    width_m: Optional[float] = Field(default=None, gt=0)
    depth_m: Optional[float] = Field(default=None, gt=0)
    num_rooms: Optional[int] = Field(default=None, ge=1)
    rooms: Optional[List[RoomSpec]] = None
    stories: int = Field(default=1, ge=1, le=3)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        json_schema_extra = {
            "example": {
                "structure_type": "residential",
                "target_area_sqm": 150,
                "num_rooms": 3,
                "rooms": [
                    {"name": "Living Room", "room_type": "living", "min_area_sqm": 25},
                    {"name": "Master Bedroom", "room_type": "bedroom", "min_area_sqm": 15},
                    {"name": "Kitchen", "room_type": "kitchen", "min_area_sqm": 10},
                ]
            }
        }


class PerimeterSketch(BaseModel):
    """Polygon sketch for building footprint."""
    points: List[List[float]]  # [[x1, y1], [x2, y2], ...] in meters
    door_wall_index: int = Field(default=0, ge=0)  # Which wall segment has the door
    target_area_sqm: float = Field(default=0, gt=0)


class SheetRequest(BaseModel):
    """Request to generate a specific sheet."""
    sheet_type: str = Field(default="floor_plan")  # floor_plan, elevation_north, etc.
    scale: str = Field(default="1:50")
    sheet_size: str = Field(default="ARCH_D")
    title: str = "Floor Plan"


class PermitPackageRequest(BaseModel):
    """Request to generate complete permit package."""
    project_name: str = "Residential Project"
    address: str = ""
    include_site_plan: bool = False
    sheet_size: str = "ARCH_D"
    scale: str = "1:50"


# =============================================================================
# PROJECT STATE
# =============================================================================

class ProjectState:
    """In-memory project state (replace with DB for production)."""
    
    def __init__(self):
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.temp_dir = Path(tempfile.mkdtemp(prefix="archengine_api_"))
    
    def create_project(self, project_id: str, building_data: Dict[str, Any]) -> str:
        """Create new project and return ID."""
        project_path = self.temp_dir / project_id
        project_path.mkdir(exist_ok=True)
        
        # Save building data
        json_path = project_path / "building.json"
        with open(json_path, 'w') as f:
            json.dump(building_data, f, indent=2)
        
        self.projects[project_id] = {
            "id": project_id,
            "path": project_path,
            "json_path": json_path,
            "created": datetime.now().isoformat(),
            "building_data": building_data
        }
        return project_id
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.projects.get(project_id)
    
    def get_building_json(self, project_id: str) -> Optional[Path]:
        project = self.projects.get(project_id)
        if project:
            return project["json_path"]
        return None


# Global state
project_state = ProjectState()


# =============================================================================
# API LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    print("🚀 Archengine Headless API starting...")
    print(f"📁 Temp directory: {project_state.temp_dir}")
    yield
    # Cleanup
    print("🧹 Cleaning up...")
    shutil.rmtree(project_state.temp_dir, ignore_errors=True)


app = FastAPI(
    title="Archengine Headless API",
    description="Programmatic access to Archengine architectural generation",
    version="0.1.0",
    lifespan=lifespan
)


# =============================================================================
# BUILDING GENERATION
# =============================================================================

@app.post("/api/v1/buildings/generate")
async def generate_building(request: BuildingRequest) -> Dict[str, Any]:
    """
    Generate a new building from specifications.
    
    Returns project ID for subsequent operations.
    """
    # TODO: Integrate with actual solver suite
    # For now, generate basic structure
    
    building_data = {
        "structure_type": request.structure_type,
        "target_area_sqm": request.target_area_sqm,
        "stories": request.stories,
        "generated_at": datetime.now().isoformat(),
        # Placeholder - integrate with actual solver
        "walls": [],
        "rooms": [],
        "doors": [],
        "windows": []
    }
    
    # Create rooms if specified
    if request.rooms:
        for i, room_spec in enumerate(request.rooms):
            building_data["rooms"].append({
                "id": f"room_{i}",
                "name": room_spec.name,
                "room_type": room_spec.room_type,
                "min_area_sqm": room_spec.min_area_sqm,
                "preferred_adjacencies": room_spec.preferred_adjacencies,
                "required_adjacencies": room_spec.required_adjacencies
            })
    
    # Generate project ID
    import uuid
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    project_state.create_project(project_id, building_data)
    
    return {
        "project_id": project_id,
        "status": "generated",
        "structure_type": request.structure_type,
        "target_area_sqm": request.target_area_sqm,
        "num_rooms": len(building_data["rooms"]),
        "next_steps": [
            f"GET /api/v1/buildings/{project_id}/solve - Run spatial solver",
            f"GET /api/v1/buildings/{project_id}/sheets/floor_plan.svg - Generate floor plan"
        ]
    }


@app.post("/api/v1/buildings/sketch")
async def generate_from_sketch(sketch: PerimeterSketch) -> Dict[str, Any]:
    """
    Generate building from perimeter sketch.
    
    User draws polygon, specifies door wall. System generates interior.
    """
    # TODO: Integrate with solver that takes perimeter as constraint
    
    import uuid
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    
    building_data = {
        "perimeter": sketch.points,
        "door_wall_index": sketch.door_wall_index,
        "target_area_sqm": sketch.target_area_sqm,
        "generated_at": datetime.now().isoformat(),
        "walls": [],  # Will be generated from perimeter
        "rooms": []
    }
    
    project_state.create_project(project_id, building_data)
    
    return {
        "project_id": project_id,
        "status": "sketch_received",
        "perimeter_points": len(sketch.points),
        "message": "Perimeter sketch accepted. Run solver to generate interior layout."
    }


@app.post("/api/v1/buildings/{project_id}/solve")
async def solve_building(
    project_id: str, 
    solver_type: str = "hybrid",
    apply_refiner: bool = True
) -> Dict[str, Any]:
    """
    Run spatial solver on building with optional refining pass.
    
    Available solvers: grid, wave_collapse, tree, perfect_adjacency,
    constraint, genetic, annealing, force_directed, space_colonization, hybrid
    
    The refining pass removes walls for open spaces and adds doors/windows.
    """
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not SOLVER_AVAILABLE:
        raise HTTPException(
            status_code=503, 
            detail="Solver not available. Check server configuration."
        )
    
    building_data = project["building_data"]
    
    try:
        # Create spatial graph from building spec
        graph = SpatialGraph()
        
        # Add rooms from building data
        for room in building_data.get("rooms", []):
            graph.add_room(
                room_id=room["name"].lower().replace(" ", "_"),
                room_type=room["room_type"],
                min_area=room["min_area_sqm"] * 10.764  # Convert sqm to sqft
            )
        
        # Add adjacencies
        for room in building_data.get("rooms", []):
            room_id = room["name"].lower().replace(" ", "_")
            for adj in room.get("required_adjacencies", []):
                graph.connect(room_id, adj.lower().replace(" ", "_"))
            for adj in room.get("preferred_adjacencies", []):
                graph.adjacent(room_id, adj.lower().replace(" ", "_"))
        
        # Get building dimensions
        width_ft = (building_data.get("width_m") or 40) * 3.28084
        depth_ft = (building_data.get("depth_m") or 30) * 3.28084
        
        # Create solver
        suite = CompleteSolverSuite(graph, width_ft, depth_ft, grid_size=2.0)
        
        # Map solver type string to enum
        solver_map = {
            "grid": SolverType.GRID,
            "wave_collapse": SolverType.WAVE_COLLAPSE,
            "tree": SolverType.TREE,
            "perfect_adjacency": SolverType.PERFECT_ADJACENCY,
            "constraint": SolverType.CONSTRAINT,
            "genetic": SolverType.GENETIC,
            "annealing": SolverType.ANNEALING,
            "force_directed": SolverType.FORCE_DIRECTED,
            "space_colonization": SolverType.SPACE_COLONIZATION,
            "hybrid": SolverType.HYBRID,
        }
        
        solver_enum = solver_map.get(solver_type, SolverType.HYBRID)
        
        # Run solver
        layout = suite.solve(solver_enum, max_iterations=50000)
        
        # Apply refining pass if requested
        if apply_refiner and layout.is_complete:
            refiner = LayoutRefiner(layout)
            
            # Auto-apply common fragments based on structure type
            structure_type = building_data.get("structure_type", "residential")
            
            if structure_type == "residential":
                # Open plan for public areas
                refiner.apply_fragment(DesignFragment.OPEN_PLAN, None)
                # Private wing for bedrooms
                refiner.apply_fragment(DesignFragment.PRIVATE_WING, None)
                # Efficient circulation
                refiner.apply_fragment(DesignFragment.EFFICIENT_CIRCULATION, None)
                # Maximize light
                refiner.apply_fragment(DesignFragment.MAXIMIZE_LIGHT, None)
            
            elif structure_type == "workshop":
                refiner.apply_fragment(DesignFragment.WORKSHOP_LAYOUT, None)
            
            elif structure_type == "garage":
                refiner.apply_fragment(DesignFragment.GARAGE_ACCESS, None)
            
            # Get refined layout
            refined_layout = refiner.get_refined_layout()
            
            # Convert to building data format
            building_data["rooms"] = [
                {
                    "id": room_id,
                    "name": room_id.replace("_", " ").title(),
                    "bounds": {
                        "x": room.rect.x * 0.3048 * 1000,  # ft to mm
                        "y": room.rect.y * 0.3048 * 1000,
                        "width": room.rect.width * 0.3048 * 1000,
                        "height": room.rect.height * 0.3048 * 1000,
                    },
                    "area_sqm": room.area * 0.092903
                }
                for room_id, room in refined_layout.rooms.items()
                if not room_id.startswith("dead_space_")
            ]
            
            building_data["walls"] = []
            for wall in refined_layout.walls:
                wall_data = {
                    "id": wall.wall_id,
                    "start": [wall.start.x * 0.3048 * 1000, 0, wall.start.y * 0.3048 * 1000],
                    "end": [wall.end.x * 0.3048 * 1000, 0, wall.end.y * 0.3048 * 1000],
                    "room1": wall.room1,
                    "room2": wall.room2,
                    "wall_type": wall.wall_type.value if hasattr(wall.wall_type, 'value') else str(wall.wall_type),
                }
                
                # Add openings
                if wall.openings:
                    wall_data["openings"] = [
                        {
                            "start": [o[0].x * 0.3048 * 1000, 0, o[0].y * 0.3048 * 1000],
                            "end": [o[1].x * 0.3048 * 1000, 0, o[1].y * 0.3048 * 1000],
                            "type": o[2].value if hasattr(o[2], 'value') else str(o[2])
                        }
                        for o in wall.openings
                    ]
                
                building_data["walls"].append(wall_data)
            
            building_data["refinements"] = refined_layout.refinements
            
            result_layout = refined_layout
        else:
            result_layout = layout
        
        # Update project
        project["building_data"] = building_data
        with open(project["json_path"], 'w') as f:
            json.dump(building_data, f, indent=2)
        
        return {
            "project_id": project_id,
            "solver": solver_type,
            "status": "solved" if result_layout.is_complete else "partial",
            "rooms_placed": len(result_layout.rooms),
            "rooms_total": len(building_data.get("rooms", [])),
            "walls_generated": len(result_layout.walls),
            "score": result_layout.score,
            "refining_pass": apply_refiner,
            "next_steps": [
                f"GET /api/v1/buildings/{project_id}/sheets/floor_plan.svg - Generate floor plan"
            ]
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Solver failed: {str(e)}")


# =============================================================================
# SHEET GENERATION
# =============================================================================

@app.get("/api/v1/buildings/{project_id}/sheets/{sheet_type}.svg")
async def get_sheet_svg(
    project_id: str,
    sheet_type: str,
    scale: str = "1:50",
    sheet_size: str = "ARCH_D"
) -> FileResponse:
    """
    Generate and return a drawing sheet as SVG.
    
    Sheet types: floor_plan, roof_plan, elevation_north, elevation_south,
    elevation_east, elevation_west, section_a, section_b
    """
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    json_path = project["json_path"]
    
    # Map sheet type to title
    titles = {
        "floor_plan": "Floor Plan",
        "roof_plan": "Roof Plan",
        "elevation_north": "North Elevation",
        "elevation_south": "South Elevation",
        "elevation_east": "East Elevation",
        "elevation_west": "West Elevation",
        "section_a": "Building Section A",
        "section_b": "Building Section B",
    }
    
    try:
        # Generate sheet
        sheet = InteractiveSheet(
            json_path=json_path,
            sheet_size=sheet_size,
            scale=scale,
            title=titles.get(sheet_type, sheet_type.replace("_", " ").title()),
            sheet_number=f"A-{list(titles.keys()).index(sheet_type) + 101 if sheet_type in titles else 999}"
        )
        
        # Save to temp file
        output_path = project["path"] / f"{sheet_type}.svg"
        sheet.save(output_path)
        
        return FileResponse(
            output_path,
            media_type="image/svg+xml",
            filename=f"{project_id}_{sheet_type}.svg"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sheet generation failed: {str(e)}")


@app.get("/api/v1/buildings/{project_id}/sheets")
async def list_available_sheets(project_id: str) -> Dict[str, Any]:
    """List all available sheets for a project."""
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    sheets = [
        {"id": "floor_plan", "name": "Floor Plan", "category": "Plans"},
        {"id": "roof_plan", "name": "Roof Plan", "category": "Plans"},
        {"id": "elevation_north", "name": "North Elevation", "category": "Elevations"},
        {"id": "elevation_south", "name": "South Elevation", "category": "Elevations"},
        {"id": "elevation_east", "name": "East Elevation", "category": "Elevations"},
        {"id": "elevation_west", "name": "West Elevation", "category": "Elevations"},
        {"id": "section_a", "name": "Building Section A", "category": "Sections"},
        {"id": "section_b", "name": "Building Section B", "category": "Sections"},
    ]
    
    return {
        "project_id": project_id,
        "sheets": sheets,
        "base_url": f"/api/v1/buildings/{project_id}/sheets/{{sheet_id}}.svg"
    }


# =============================================================================
# PDF EXPORT
# =============================================================================

@app.post("/api/v1/buildings/{project_id}/export/pdf")
async def export_pdf(
    project_id: str,
    request: PermitPackageRequest
) -> FileResponse:
    """
    Export complete drawing set as PDF.
    
    Returns permit-ready PDF with all sheets.
    """
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # TODO: Integrate with pdf_export.py
    # For now, return placeholder message
    
    raise HTTPException(
        status_code=501,
        detail="PDF export integration pending. Use SVG endpoints for now."
    )


# =============================================================================
# CONSTRAINT & FRAGMENT API (QBD Algebra)
# =============================================================================

@app.post("/api/v1/buildings/{project_id}/constraints/add")
async def add_constraint(
    project_id: str,
    constraint: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Add a constraint to the building.
    
    Examples:
    - {"type": "min_area", "target": "living_room", "value": 25}
    - {"type": "adjacency", "room_a": "kitchen", "room_b": "dining", "required": true}
    - {"type": "aspect_ratio", "room": "bedroom", "min": 0.5, "max": 2.0}
    """
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # TODO: Integrate with QBD algebra constraint system
    
    return {
        "project_id": project_id,
        "constraint_added": constraint,
        "status": "pending_resolve",
        "message": "Constraint added. Run /solve to regenerate layout."
    }


@app.post("/api/v1/buildings/{project_id}/fragments/apply")
async def apply_fragment(
    project_id: str,
    fragment: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Apply a design fragment to the building.
    
    Fragments are high-level design intentions:
    - {"fragment": "open_plan", "rooms": ["kitchen", "living", "dining"]}
    - {"fragment": "private_wing", "rooms": ["bedroom", "bathroom"], "side": "rear"}
    - {"fragment": "garage_access", "side": "side"}
    - {"fragment": "maximize_light", "rooms": ["living", "bedroom"]}
    - {"fragment": "efficient_circulation"}
    """
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not SOLVER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Solver not available")
    
    fragment_type = fragment.get("fragment", "")
    room_ids = fragment.get("rooms", [])
    
    # Map fragment names to DesignFragment enum
    fragment_map = {
        "open_plan": DesignFragment.OPEN_PLAN,
        "private_wing": DesignFragment.PRIVATE_WING,
        "garage_access": DesignFragment.GARAGE_ACCESS,
        "workshop_layout": DesignFragment.WORKSHOP_LAYOUT,
        "efficient_circulation": DesignFragment.EFFICIENT_CIRCULATION,
        "maximize_light": DesignFragment.MAXIMIZE_LIGHT,
        "storage_optimized": DesignFragment.STORAGE_OPTIMIZED,
    }
    
    design_fragment = fragment_map.get(fragment_type)
    if not design_fragment:
        raise HTTPException(status_code=400, detail=f"Unknown fragment: {fragment_type}")
    
    # Note: In full implementation, we'd reload the PlacedLayout from building_data,
    # apply the fragment, and regenerate. For now, store the fragment request
    # for next solve.
    
    building_data = project["building_data"]
    if "design_fragments" not in building_data:
        building_data["design_fragments"] = []
    
    building_data["design_fragments"].append(fragment)
    
    # Save updated building data
    with open(project["json_path"], 'w') as f:
        json.dump(building_data, f, indent=2)
    
    return {
        "project_id": project_id,
        "fragment_applied": fragment,
        "status": "stored",
        "message": f"Fragment '{fragment_type}' stored. Run /solve to apply to layout."
    }


# =============================================================================
# PROJECT MANAGEMENT
# =============================================================================

@app.get("/api/v1/buildings/{project_id}")
async def get_project_info(project_id: str) -> Dict[str, Any]:
    """Get project details and current state."""
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {
        "project_id": project_id,
        "created": project["created"],
        "structure_type": project["building_data"].get("structure_type"),
        "target_area_sqm": project["building_data"].get("target_area_sqm"),
        "num_rooms": len(project["building_data"].get("rooms", [])),
        "endpoints": {
            "solve": f"/api/v1/buildings/{project_id}/solve",
            "sheets": f"/api/v1/buildings/{project_id}/sheets",
            "export_pdf": f"/api/v1/buildings/{project_id}/export/pdf"
        }
    }


@app.delete("/api/v1/buildings/{project_id}")
async def delete_project(project_id: str) -> Dict[str, Any]:
    """Delete a project and all associated files."""
    project = project_state.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Delete directory
    shutil.rmtree(project["path"], ignore_errors=True)
    del project_state.projects[project_id]
    
    return {"project_id": project_id, "status": "deleted"}


@app.get("/api/v1/buildings")
async def list_projects() -> Dict[str, Any]:
    """List all active projects."""
    projects = []
    for pid, proj in project_state.projects.items():
        projects.append({
            "project_id": pid,
            "created": proj["created"],
            "structure_type": proj["building_data"].get("structure_type")
        })
    
    return {"projects": projects, "count": len(projects)}


# =============================================================================
# HEALTH & INFO
# =============================================================================

@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "archengine-headless"}


@app.get("/")
async def root() -> Dict[str, Any]:
    """API information."""
    return {
        "name": "Archengine Headless API",
        "version": "0.1.0",
        "description": "Programmatic architectural generation",
        "endpoints": {
            "generate_building": "POST /api/v1/buildings/generate",
            "generate_from_sketch": "POST /api/v1/buildings/sketch",
            "solve": "POST /api/v1/buildings/{id}/solve",
            "get_sheet": "GET /api/v1/buildings/{id}/sheets/{type}.svg",
            "export_pdf": "POST /api/v1/buildings/{id}/export/pdf",
            "add_constraint": "POST /api/v1/buildings/{id}/constraints/add",
            "apply_fragment": "POST /api/v1/buildings/{id}/fragments/apply"
        },
        "documentation": "/docs"
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
