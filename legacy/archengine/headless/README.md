# Archengine Headless

Run Archengine without the GUI. API-first, AI-ready architecture.

## Overview

Headless Archengine provides programmatic access to the spatial solvers, sheet generators, and PDF export — without the PyQt6 interface. Perfect for:

- AI integration (MCP server for Claude)
- Batch processing
- Custom frontends
- AR/VR pipelines
- Permit automation

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Input         │────▶│   Archengine     │────▶│   Output        │
│   (JSON/API)    │     │   Headless       │     │   (SVG/PDF)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌──────────────────┐
│   MCP Server    │     │   9 Solvers      │
│   (Claude)      │     │   Sheet Gen      │
└─────────────────┘     └──────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
cd /root/ArchEngine/headless
pip install -r requirements.txt
```

### 2. Start API Server

```bash
python api_server.py
```

Server runs at `http://localhost:8000`

### 3. Test with curl

```bash
# Generate a building
curl -X POST http://localhost:8000/api/v1/buildings/generate \
  -H "Content-Type: application/json" \
  -d '{
    "structure_type": "residential",
    "target_area_sqm": 150,
    "num_rooms": 3,
    "rooms": [
      {"name": "Living Room", "room_type": "living", "min_area_sqm": 25},
      {"name": "Master Bedroom", "room_type": "bedroom", "min_area_sqm": 15},
      {"name": "Kitchen", "room_type": "kitchen", "min_area_sqm": 10}
    ]
  }'

# Response: {"project_id": "proj_abc123", ...}

# Get floor plan SVG
curl -O http://localhost:8000/api/v1/buildings/proj_abc123/sheets/floor_plan.svg

# Export permit package
curl -X POST http://localhost:8000/api/v1/buildings/proj_abc123/export/pdf \
  -H "Content-Type: application/json" \
  -d '{"project_name": "My House", "address": "123 Main St"}'
```

## API Endpoints

### Building Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/buildings/generate` | Generate from specs |
| POST | `/api/v1/buildings/sketch` | Generate from perimeter sketch |
| POST | `/api/v1/buildings/{id}/solve` | Run spatial solver |
| GET | `/api/v1/buildings/{id}` | Get project info |
| DELETE | `/api/v1/buildings/{id}` | Delete project |
| GET | `/api/v1/buildings` | List all projects |

### Sheet Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/buildings/{id}/sheets` | List available sheets |
| GET | `/api/v1/buildings/{id}/sheets/floor_plan.svg` | Floor plan |
| GET | `/api/v1/buildings/{id}/sheets/elevation_north.svg` | North elevation |
| GET | `/api/v1/buildings/{id}/sheets/section_a.svg` | Section A |

### Constraints & Fragments

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/buildings/{id}/constraints/add` | Add hard constraint |
| POST | `/api/v1/buildings/{id}/fragments/apply` | Apply design fragment |

### Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/buildings/{id}/export/pdf` | Permit package PDF |

## MCP Server (Claude Integration)

The MCP server allows Claude to call Archengine directly as a tool.

### Setup

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "archengine": {
      "command": "python",
      "args": ["/root/ArchEngine/headless/mcp_server.py"]
    }
  }
}
```

### Available Tools

Claude can use these tools:

- `generate_building` - Create building from specs
- `generate_from_sketch` - Create from perimeter polygon
- `get_floor_plan` - Generate floor plan SVG
- `get_elevation` - Generate elevation
- `apply_design_fragment` - Apply design patterns (open_plan, private_wing, etc.)
- `add_constraint` - Add hard constraints (min_area, adjacency, etc.)
- `export_permit_package` - Export PDF package
- `get_building_info` - Get project details

### Example Conversation

**User:** "Design a 3-bedroom house, 150 square meters, with an open kitchen-living area."

**Claude:** 
1. Calls `generate_building` with residential specs
2. Calls `apply_design_fragment` with "open_plan" for kitchen/living
3. Calls `get_floor_plan` to show SVG
4. Returns: "Here's your floor plan..."

**User:** "Move the master bedroom to the back for privacy."

**Claude:**
1. Calls `apply_design_fragment` with "private_wing" 
2. Regenerates floor plan
3. Returns updated drawing

## Design Fragments

Fragments are high-level design intentions:

| Fragment | Effect |
|----------|--------|
| `open_plan` | Combine kitchen/living/dining |
| `private_wing` | Group bedrooms away from public areas |
| `garage_access` | Optimize garage entry |
| `maximize_light` | Prioritize window placement |
| `efficient_circulation` | Minimize hallway space |
| `workshop_layout` | Tool workflow optimization |
| `storage_optimized` | Maximize closet/storage |

## Constraints

Hard requirements the solver must satisfy:

| Constraint | Parameters |
|------------|------------|
| `min_area` | target room, value (sqm) |
| `max_area` | target room, value (sqm) |
| `adjacency` | room_a, room_b, required (bool) |
| `aspect_ratio` | room, min, max |
| `window_required` | room, side (north/south/etc) |
| `setback` | distance, side |

## Universal Interface

All structure types use the same 3 inputs:

1. **Polygon sketch** - Perimeter points (4-8 vertices)
2. **Target area** - Validates/adjusts sketch
3. **Door wall** - Click wall segment for entry

Works for:
- **Residential** - Room adjacencies, privacy gradients
- **Shed** - Simple enclosure, door placement
- **Garage** - Vehicle bays, clearance
- **Workshop** - Tool workflow, power

## Metric Dimensioning

All dimensions in metric:
- Millimeters for details (e.g., "2400")
- Meters for large dimensions (e.g., "3.6 m")
- 4-side dimensioning (top, bottom, left, right)
- Consolidated chains (skips segments < 300mm)

## Development Status

| Feature | Status |
|---------|--------|
| API server | ✅ Implemented |
| MCP server | ✅ Implemented |
| Sheet generation | ⚠️ Needs integration |
| PDF export | ⚠️ Needs integration |
| Solver integration | ⚠️ Needs integration |
| QBD algebra | ⚠️ Needs integration |

## Next Steps

1. **Integrate solvers** - Connect `api_server.py` to `CompleteSolverSuite`
2. **Test dimensioning** - Generate test floor plan, verify accuracy
3. **PDF export** - Bridge to `pdf_export.py`
4. **Elevations** - Enhance elevation renderer
5. **Site plan** - Add topography integration

## Files

- `api_server.py` - FastAPI REST server
- `mcp_server.py` - Model Context Protocol server
- `requirements.txt` - Python dependencies
- `README.md` - This file

---

**Goal:** First permit submission within 4 weeks.
