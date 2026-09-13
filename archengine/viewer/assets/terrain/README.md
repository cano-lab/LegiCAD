# Terrain JSON Format Specification

The terrain JSON format provides a simple way to define custom topography for site visualization without requiring GeoTIFF data.

## Structure

```json
{
  "name": "Site Name",
  "description": "Optional description of the terrain",
  "grid": {
    "width": <float>,      // Width of the site in meters
    "depth": <float>,      // Depth of the site in meters  
    "resolution": <int>,   // Number of sample points along each axis
    "base_elevation": <float> // Optional base elevation offset in meters
  },
  "elevations": [          // 2D array of elevation values
    [z00, z01, z02, ...],
    [z10, z11, z12, ...],
    ...
  ]
}
```

## Grid Details

- **width/depth**: Physical dimensions of the terrain grid in meters
- **resolution**: Number of sample points (not cells). A resolution of 10 creates an 11×11 grid of elevation points
- **base_elevation**: Optional offset added to all elevation values (default: 0.0)

## Elevations Array

- 2D array with dimensions `(resolution+1) × (resolution+1)`
- Values represent elevation in meters relative to base_elevation
- Array indices correspond to positions from corner (0,0) to (width, depth)
- Row 0 is the "back" of the site, last row is the "front"

## Example Usage

```bash
# Run viewer with custom terrain
./target/release/archview-massing --terrain-json path/to/terrain.json --lot-width 20 --lot-depth 40 --bylaw R1
```

## Included Samples

| File | Description | Use Case |
|------|-------------|----------|
| `flat.json` | Completely flat terrain | Simple suburban lots |
| `gentle_slope.json` | Uniform south-facing slope | Typical residential grading |
| `hillside.json` | Prominent central hill | Elevated home sites |
| `valley.json` | Low center with high sides | Creek valley properties |
| `waterfront.json` | Slope down to water | Lake/riverfront lots |

## Creating Custom Terrain

1. Determine your site dimensions (width × depth in meters)
2. Choose a resolution (5-20 is typical for visualization)
3. Measure or estimate elevations at grid points
4. Create the JSON file following the structure above
5. Load it with `--terrain-json` flag

## Tips

- Keep resolution modest (≤20) for quick loading and smooth performance
- Elevations can be negative (below datum)
- For real sites, consider using GeoTIFF with actual LiDAR data instead
- The terrain extends beyond the lot bounds for visual context
