"""
Solver API routes for room layout generation.

Provides REST API endpoints for running layout solvers.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from complete_solver_suite import CompleteSolverSuite, SolverType, SOLVER_INFO
from room_relationships import SpatialGraph, RoomNode, Zone


router = APIRouter(prefix="/solvers", tags=["solvers"])


class RoomDefinition(BaseModel):
    """Room definition for solver input."""
    id: str
    room_type: str = "room"
    min_area: float = Field(default=10.0, ge=1.0)
    target_area: float = Field(default=15.0, ge=1.0)
    min_width: float = Field(default=2.5, ge=1.0)
    min_depth: float = Field(default=2.5, ge=1.0)
    zone: str = "private"
    floor: int = Field(default=0, ge=0)


class AdjacencyDefinition(BaseModel):
    """Adjacency relationship between rooms."""
    room_a: str
    room_b: str
    weight: float = Field(default=1.0, ge=0.0)


class SolverRequest(BaseModel):
    """Request body for running a solver."""
    rooms: List[RoomDefinition]
    adjacencies: List[AdjacencyDefinition] = []
    width: float = Field(default=15.0, ge=5.0, le=100.0)
    depth: float = Field(default=12.0, ge=5.0, le=100.0)
    grid_size: float = Field(default=0.5, ge=0.1, le=2.0)
    max_iterations: int = Field(default=10000, ge=100, le=100000)


class PlacedRoomResponse(BaseModel):
    """Placed room in output layout."""
    id: str
    x: float
    y: float
    z: float
    width: float
    depth: float
    height: float = 2.7
    area: float


class SolverMetadataResponse(BaseModel):
    """Solver metadata response."""
    solver_type: str
    name: str
    description: str
    speed: str
    reliability: str
    best_for: List[str]
    characteristics: Dict[str, str]


class SolverResponse(BaseModel):
    """Response from running a solver."""
    solver_type: str
    rooms: Dict[str, PlacedRoomResponse]
    metadata: Dict[str, Any]
    score: float
    is_complete: bool
    iterations: int
    solve_time_ms: float


class CompareResponse(BaseModel):
    """Response from comparing all solvers."""
    results: Dict[str, SolverResponse]
    building_width: float
    building_depth: float


def _build_graph(request: SolverRequest) -> SpatialGraph:
    """Build spatial graph from request."""
    graph = SpatialGraph()

    zone_map = {
        "public": Zone.PUBLIC,
        "private": Zone.PRIVATE,
        "service": Zone.SERVICE,
        "circulation": Zone.CIRCULATION,
    }

    for room_def in request.rooms:
        graph.add_room(
            room_id=room_def.id,
            room_type=room_def.room_type,
            min_area=room_def.min_area,
            target_area=room_def.target_area,
            min_width=room_def.min_width,
            min_depth=room_def.min_depth,
            zone=zone_map.get(room_def.zone, Zone.PRIVATE),
            floor=room_def.floor,
        )

    for adj in request.adjacencies:
        graph.connect(adj.room_a, adj.room_b, adj.weight)

    return graph


def _layout_to_response(solver_type: SolverType, layout) -> SolverResponse:
    """Convert layout to response model."""
    rooms = {}
    for room_id, placed in layout.rooms.items():
        rooms[room_id] = PlacedRoomResponse(
            id=room_id,
            x=placed.rect.x,
            y=0,
            z=placed.rect.y,
            width=placed.rect.width,
            depth=placed.rect.height,
            height=2.7,
            area=placed.area,
        )

    return SolverResponse(
        solver_type=solver_type.value,
        rooms=rooms,
        metadata={
            "overlaps": len(layout.get_overlaps()),
            "total_area": layout.total_area(),
            "coverage": layout.coverage(
                sum(r.width for r in rooms.values()),
                sum(r.depth for r in rooms.values())
            ) if rooms else 0,
        },
        score=layout.score,
        is_complete=layout.is_complete,
        iterations=layout.iterations,
        solve_time_ms=layout.solve_time_ms,
    )


@router.get("/list", response_model=List[SolverMetadataResponse])
async def list_solvers():
    """List all available solver algorithms with metadata."""
    solvers = []
    for solver_type in SolverType:
        info = SOLVER_INFO.get(solver_type)
        if not info:
            continue

        solvers.append(SolverMetadataResponse(
            solver_type=solver_type.value,
            name=info.name,
            description=info.description,
            speed=info.speed,
            reliability=info.reliability,
            best_for=info.best_for,
            characteristics=info.characteristics,
        ))

    return solvers


@router.post("/solve/{solver_type}", response_model=SolverResponse)
async def solve_layout(solver_type: str, request: SolverRequest):
    """
    Generate a room layout using the specified solver algorithm.

    - **solver_type**: The algorithm to use (grid, tree, wave_collapse, etc.)
    - **request**: Room definitions and constraints
    """
    # Validate solver type
    try:
        st = SolverType(solver_type.lower())
    except ValueError:
        valid = [s.value for s in SolverType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid solver type. Valid options: {valid}"
        )

    # Build graph and run solver
    graph = _build_graph(request)

    errors = graph.validate()
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    suite = CompleteSolverSuite(graph, request.width, request.depth, request.grid_size)

    try:
        layout = suite.solve(st, max_iterations=request.max_iterations)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Solver failed: {str(e)}")

    return _layout_to_response(st, layout)


@router.post("/compare", response_model=CompareResponse)
async def compare_solvers(request: SolverRequest):
    """
    Run all solvers and return results for comparison.

    Useful for evaluating which algorithm works best for your specific layout.
    """
    graph = _build_graph(request)

    errors = graph.validate()
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    suite = CompleteSolverSuite(graph, request.width, request.depth, request.grid_size)

    results = {}
    for solver_type, layout in suite.solve_all(max_iterations=request.max_iterations).items():
        results[solver_type.value] = _layout_to_response(solver_type, layout)

    return CompareResponse(
        results=results,
        building_width=request.width,
        building_depth=request.depth,
    )


@router.post("/solve/best", response_model=SolverResponse)
async def solve_with_best(request: SolverRequest):
    """
    Run multiple solvers and return the best result.

    Uses the Hybrid solver which internally runs multiple algorithms
    and selects the best layout.
    """
    graph = _build_graph(request)

    errors = graph.validate()
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    suite = CompleteSolverSuite(graph, request.width, request.depth, request.grid_size)

    try:
        layout = suite.solve(SolverType.HYBRID, max_iterations=request.max_iterations)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Solver failed: {str(e)}")

    return _layout_to_response(SolverType.HYBRID, layout)
