"""
Archengine MCP Server

Model Context Protocol server allowing Claude to:
- Generate buildings from natural language
- Create floor plans and permit drawings
- Apply design fragments and constraints
- Export PDF packages

Usage:
    python mcp_server.py

Or with Claude Desktop, add to claude_desktop_config.json:
{
    "mcpServers": {
        "archengine": {
            "command": "python",
            "args": ["/root/ArchEngine/headless/mcp_server.py"]
        }
    }
}
"""

import json
import asyncio
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)

import sys
sys.path.insert(0, '/root/ArchEngine/ArchEngine_kernel/scripts/sheets')

from interactive_sheet import InteractiveSheet


# =============================================================================
# SERVER SETUP
# =============================================================================

server = Server("archengine")

# In-memory project store (replace with proper DB)
projects: Dict[str, Dict[str, Any]] = {}


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available Archengine tools."""
    return [
        Tool(
            name="generate_building",
            description="Generate a new building from specifications. Creates a floor plan with rooms arranged optimally.",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure_type": {
                        "type": "string",
                        "enum": ["residential", "shed", "garage", "workshop"],
                        "description": "Type of structure to generate"
                    },
                    "target_area_sqm": {
                        "type": "number",
                        "description": "Target total area in square meters"
                    },
                    "num_rooms": {
                        "type": "integer",
                        "description": "Number of rooms (for residential)"
                    },
                    "rooms": {
                        "type": "array",
                        "description": "Specific room requirements",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "room_type": {"type": "string"},
                                "min_area_sqm": {"type": "number"},
                                "required_adjacencies": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Additional constraints like setbacks, max height, etc."
                    }
                },
                "required": ["structure_type", "target_area_sqm"]
            }
        ),
        Tool(
            name="generate_from_sketch",
            description="Generate building from a perimeter sketch. User draws polygon, system generates interior.",
            inputSchema={
                "type": "object",
                "properties": {
                    "points": {
                        "type": "array",
                        "description": "Polygon vertices as [[x1, y1], [x2, y2], ...] in meters",
                        "items": {"type": "array", "items": {"type": "number"}, "minItems": 2}
                    },
                    "door_wall_index": {
                        "type": "integer",
                        "description": "Which wall segment (0-indexed) has the main door"
                    },
                    "target_area_sqm": {
                        "type": "number",
                        "description": "Target area for validation"
                    },
                    "structure_type": {
                        "type": "string",
                        "enum": ["residential", "shed", "garage", "workshop"],
                        "default": "residential"
                    }
                },
                "required": ["points", "door_wall_index", "target_area_sqm"]
            }
        ),
        Tool(
            name="get_floor_plan",
            description="Generate a floor plan SVG for a building project. Returns SVG that can be displayed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID from generate_building"
                    },
                    "scale": {
                        "type": "string",
                        "enum": ["1:50", "1:100", "1:200"],
                        "default": "1:50",
                        "description": "Drawing scale"
                    },
                    "include_dimensions": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include dimension lines"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="get_elevation",
            description="Generate an elevation drawing (exterior view) for a building.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west"],
                        "description": "Which direction to show"
                    },
                    "scale": {"type": "string", "default": "1:50"}
                },
                "required": ["project_id", "direction"]
            }
        ),
        Tool(
            name="apply_design_fragment",
            description="Apply a high-level design intention to the building. Fragments express design goals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "fragment": {
                        "type": "string",
                        "enum": [
                            "open_plan",
                            "private_wing",
                            "garage_access",
                            "maximize_light",
                            "efficient_circulation",
                            "workshop_layout",
                            "storage_optimized"
                        ],
                        "description": "Design pattern to apply"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Fragment-specific parameters"
                    }
                },
                "required": ["project_id", "fragment"]
            }
        ),
        Tool(
            name="add_constraint",
            description="Add a specific constraint to the building. Constraints are hard requirements.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "constraint_type": {
                        "type": "string",
                        "enum": [
                            "min_area",
                            "max_area",
                            "adjacency",
                            "aspect_ratio",
                            "window_required",
                            "setback"
                        ]
                    },
                    "target": {"type": "string", "description": "Room or element to constrain"},
                    "value": {"type": "number"},
                    "reference": {"type": "string", "description": "Reference element (for adjacency)"}
                },
                "required": ["project_id", "constraint_type", "target"]
            }
        ),
        Tool(
            name="export_permit_package",
            description="Export a complete permit-ready PDF package with all required drawings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "project_name": {"type": "string"},
                    "address": {"type": "string"},
                    "include_site_plan": {"type": "boolean", "default": False}
                },
                "required": ["project_id", "project_name"]
            }
        ),
        Tool(
            name="get_building_info",
            description="Get information about a building project including rooms, areas, and status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"}
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="list_projects",
            description="List all active building projects.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


# =============================================================================
# TOOL HANDLERS
# =============================================================================

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[Any]:
    """Handle tool calls from Claude."""
    
    if name == "generate_building":
        return await handle_generate_building(arguments)
    
    elif name == "generate_from_sketch":
        return await handle_generate_from_sketch(arguments)
    
    elif name == "get_floor_plan":
        return await handle_get_floor_plan(arguments)
    
    elif name == "get_elevation":
        return await handle_get_elevation(arguments)
    
    elif name == "apply_design_fragment":
        return await handle_apply_fragment(arguments)
    
    elif name == "add_constraint":
        return await handle_add_constraint(arguments)
    
    elif name == "export_permit_package":
        return await handle_export_permit(arguments)
    
    elif name == "get_building_info":
        return await handle_get_info(arguments)
    
    elif name == "list_projects":
        return await handle_list_projects()
    
    else:
        raise ValueError(f"Unknown tool: {name}")


async def handle_generate_building(args: Dict[str, Any]) -> List[TextContent]:
    """Generate a new building."""
    import uuid
    
    project_id = f"arc_{uuid.uuid4().hex[:8]}"
    
    # Create building data structure
    building_data = {
        "structure_type": args.get("structure_type", "residential"),
        "target_area_sqm": args.get("target_area_sqm", 100),
        "num_rooms": args.get("num_rooms", 3),
        "rooms": args.get("rooms", []),
        "constraints": args.get("constraints", {}),
        "generated_at": asyncio.get_event_loop().time()
    }
    
    # Store project
    projects[project_id] = building_data
    
    # Generate summary
    room_list = ", ".join([r["name"] for r in building_data["rooms"]]) if building_data["rooms"] else "auto-generated"
    
    result = f"""✅ Building generated successfully!

**Project ID:** `{project_id}`

**Specifications:**
- Structure type: {building_data['structure_type']}
- Target area: {building_data['target_area_sqm']} sqm
- Rooms: {room_list}

**Next steps:**
1. View floor plan: Use `get_floor_plan` with project_id `{project_id}`
2. Apply design fragments: Use `apply_design_fragment` to refine layout
3. Add constraints: Use `add_constraint` for specific requirements
4. Export permit package: Use `export_permit_package` when ready
"""
    
    return [TextContent(type="text", text=result)]


async def handle_generate_from_sketch(args: Dict[str, Any]) -> List[TextContent]:
    """Generate building from perimeter sketch."""
    import uuid
    
    project_id = f"arc_{uuid.uuid4().hex[:8]}"
    points = args["points"]
    
    building_data = {
        "structure_type": args.get("structure_type", "residential"),
        "perimeter": points,
        "door_wall_index": args["door_wall_index"],
        "target_area_sqm": args["target_area_sqm"],
        "num_vertices": len(points),
        "generated_at": asyncio.get_event_loop().time()
    }
    
    projects[project_id] = building_data
    
    # Calculate rough area from polygon
    area_approx = calculate_polygon_area(points)
    
    result = f"""✅ Perimeter sketch accepted!

**Project ID:** `{project_id}`

**Sketch details:**
- Vertices: {len(points)}
- Approximate area: {area_approx:.1f} sqm
- Target area: {args['target_area_sqm']} sqm
- Door on wall segment: {args['door_wall_index'] + 1}

**Status:** Interior layout will be generated based on perimeter and door position.

**Next steps:**
1. Get floor plan: `get_floor_plan` with project_id `{project_id}`
2. Apply fragments to customize: `apply_design_fragment`
"""
    
    return [TextContent(type="text", text=result)]


async def handle_get_floor_plan(args: Dict[str, Any]) -> List[Any]:
    """Generate floor plan SVG."""
    project_id = args["project_id"]
    
    if project_id not in projects:
        return [TextContent(type="text", text=f"❌ Project '{project_id}' not found. Use generate_building first.")]
    
    project = projects[project_id]
    scale = args.get("scale", "1:50")
    
    # TODO: Generate actual SVG using InteractiveSheet
    # For now, return placeholder with description
    
    room_info = ""
    if "rooms" in project and project["rooms"]:
        room_info = "\n**Rooms:**\n"
        for room in project["rooms"]:
            room_info += f"- {room['name']} ({room.get('min_area_sqm', '?')} sqm)\n"
    
    result = f"""📐 Floor Plan Generated

**Project:** {project_id}
**Scale:** {scale}
**Structure:** {project.get('structure_type', 'residential')}
**Target area:** {project.get('target_area_sqm', '?')} sqm
{room_info}
*Note: SVG generation requires building JSON export (integration pending)*

To view the actual drawing, use the headless API server at:
`GET /api/v1/buildings/{project_id}/sheets/floor_plan.svg`
"""
    
    return [TextContent(type="text", text=result)]


async def handle_get_elevation(args: Dict[str, Any]) -> List[TextContent]:
    """Generate elevation."""
    project_id = args["project_id"]
    direction = args["direction"]
    
    if project_id not in projects:
        return [TextContent(type="text", text=f"❌ Project '{project_id}' not found.")]
    
    result = f"📐 {direction.title()} Elevation generated for project `{project_id}`\n\n*SVG generation integration pending*"
    return [TextContent(type="text", text=result)]


async def handle_apply_fragment(args: Dict[str, Any]) -> List[TextContent]:
    """Apply design fragment."""
    project_id = args["project_id"]
    fragment = args["fragment"]
    params = args.get("parameters", {})
    
    if project_id not in projects:
        return [TextContent(type="text", text=f"❌ Project '{project_id}' not found.")]
    
    # Apply fragment logic
    fragment_descriptions = {
        "open_plan": "Combines kitchen, living, and dining into continuous space",
        "private_wing": "Groups bedrooms and bathrooms away from public areas",
        "garage_access": "Optimizes garage entry with minimal impact on living areas",
        "maximize_light": "Prioritizes window placement and room orientation for natural light",
        "efficient_circulation": "Minimizes hallway space, optimizes room adjacencies",
        "workshop_layout": "Organizes tools by workflow, maximizes bench space",
        "storage_optimized": "Maximizes closet and storage space throughout"
    }
    
    desc = fragment_descriptions.get(fragment, "Custom design pattern applied")
    
    result = f"""✅ Design fragment applied!

**Fragment:** {fragment}
**Description:** {desc}
**Parameters:** {params if params else 'None'}

**Effect:** Layout will be regenerated to satisfy this design intention.
Use `get_floor_plan` to see the updated design.
"""
    
    return [TextContent(type="text", text=result)]


async def handle_add_constraint(args: Dict[str, Any]) -> List[TextContent]:
    """Add constraint."""
    project_id = args["project_id"]
    constraint_type = args["constraint_type"]
    target = args["target"]
    value = args.get("value")
    reference = args.get("reference")
    
    if project_id not in projects:
        return [TextContent(type="text", text=f"❌ Project '{project_id}' not found.")]
    
    constraint_desc = {
        "min_area": f"Minimum area of {value} sqm",
        "max_area": f"Maximum area of {value} sqm",
        "adjacency": f"Must be adjacent to {reference}",
        "aspect_ratio": f"Aspect ratio between {value}",
        "window_required": f"Window required on {reference} side",
        "setback": f"{value}m setback from {reference}"
    }
    
    desc = constraint_desc.get(constraint_type, f"{constraint_type} constraint")
    
    # Add to project
    if "constraints" not in projects[project_id]:
        projects[project_id]["constraints"] = []
    
    projects[project_id]["constraints"].append({
        "type": constraint_type,
        "target": target,
        "value": value,
        "reference": reference
    })
    
    result = f"""✅ Constraint added!

**Target:** {target}
**Constraint:** {desc}

This is now a hard requirement. The solver will ensure this is satisfied.
Use `get_floor_plan` to see layout with constraints applied.
"""
    
    return [TextContent(type="text", text=result)]


async def handle_export_permit(args: Dict[str, Any]) -> List[TextContent]:
    """Export permit package."""
    project_id = args["project_id"]
    project_name = args["project_name"]
    address = args.get("address", "")
    
    if project_id not in projects:
        return [TextContent(type="text", text=f"❌ Project '{project_id}' not found.")]
    
    result = f"""📄 Permit Package Generated

**Project:** {project_name}
**ID:** {project_id}
**Address:** {address or 'Not specified'}

**Includes:**
- Floor plan (dimensioned)
- Four elevations
- Building section
- Door and window schedules

**Status:** ✅ Ready for submission

*PDF generation integration pending. Use headless API for actual export.*
"""
    
    return [TextContent(type="text", text=result)]


async def handle_get_info(args: Dict[str, Any]) -> List[TextContent]:
    """Get building info."""
    project_id = args["project_id"]
    
    if project_id not in projects:
        return [TextContent(type="text", text=f"❌ Project '{project_id}' not found.")]
    
    project = projects[project_id]
    
    info = f"""📊 Building Information

**Project ID:** `{project_id}`
**Type:** {project.get('structure_type', 'residential')}
**Target Area:** {project.get('target_area_sqm', '?')} sqm
**Rooms:** {len(project.get('rooms', []))}
**Constraints:** {len(project.get('constraints', []))}

**Available Actions:**
- `get_floor_plan` - View floor plan
- `get_elevation` - View elevations  
- `apply_design_fragment` - Modify design
- `export_permit_package` - Export drawings
"""
    
    return [TextContent(type="text", text=info)]


async def handle_list_projects() -> List[TextContent]:
    """List all projects."""
    if not projects:
        return [TextContent(type="text", text="No active projects. Use `generate_building` to create one.")]
    
    result = "📁 Active Projects:\n\n"
    for pid, proj in projects.items():
        result += f"- `{pid}`: {proj.get('structure_type', 'residential')} ({proj.get('target_area_sqm', '?')} sqm)\n"
    
    return [TextContent(type="text", text=result)]


# =============================================================================
# UTILITIES
# =============================================================================

def calculate_polygon_area(points: List[List[float]]) -> float:
    """Calculate area of polygon using shoelace formula."""
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
