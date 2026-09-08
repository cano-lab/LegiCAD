/**
 * ArchEngine C API - For embedding in Qt/Python applications
 *
 * This provides a simple C interface that can be called from Python via ctypes
 * to embed the Vulkan renderer in a Qt widget.
 */

#ifndef ARCH_API_H
#define ARCH_API_H

#ifdef _WIN32
    #ifdef ARCHENGINE_EXPORTS
        #define ARCH_API __declspec(dllexport)
    #else
        #define ARCH_API __declspec(dllimport)
    #endif
#else
    #define ARCH_API
#endif

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the renderer with an existing window handle.
 *
 * @param hwnd The native window handle (HWND on Windows)
 * @param width Initial width
 * @param height Initial height
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_init(void* hwnd, int width, int height);

/**
 * Initialize renderer in headless mode for offline rendering.
 * Use this for path tracing without a display.
 *
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_init_headless(void);

/**
 * Shutdown the renderer and release all resources.
 */
ARCH_API void arch_shutdown(void);

/**
 * Check if renderer is initialized.
 * @return 1 if initialized, 0 otherwise
 */
ARCH_API int arch_is_initialized(void);

/**
 * Load building data from JSON string.
 * Uses the QBD JSON format.
 *
 * @param json_str The JSON string containing building data
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_load_json(const char* json_str);

/**
 * Load building data from a file path.
 *
 * @param file_path Path to the JSON file
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_load_file(const char* file_path);

/**
 * Render a single frame.
 * Call this from the Qt paint event or a timer.
 *
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_render_frame(void);

/**
 * Handle window resize.
 *
 * @param width New width
 * @param height New height
 */
ARCH_API void arch_resize(int width, int height);

/**
 * Set camera position (orbit camera).
 *
 * @param yaw Horizontal angle in radians
 * @param pitch Vertical angle in radians
 * @param distance Distance from target
 */
ARCH_API void arch_set_camera(float yaw, float pitch, float distance);

/**
 * Set camera target/focus point.
 *
 * @param x Target X
 * @param y Target Y
 * @param z Target Z
 */
ARCH_API void arch_set_camera_target(float x, float y, float z);

/**
 * Set camera position and target directly (for free-look mode).
 *
 * @param cam_x Camera position X
 * @param cam_y Camera position Y
 * @param cam_z Camera position Z
 * @param target_x Target X
 * @param target_y Target Y
 * @param target_z Target Z
 */
ARCH_API void arch_set_camera_pose(float cam_x, float cam_y, float cam_z,
                                   float target_x, float target_y, float target_z);

/**
 * Reset camera to fit the current building.
 */
ARCH_API void arch_reset_camera(void);

/**
 * Get current camera state after reset.
 * Use this to sync Python state with C++ calculated values.
 *
 * @param out_target_x Target X (or NULL to skip)
 * @param out_target_y Target Y (or NULL to skip)
 * @param out_target_z Target Z (or NULL to skip)
 * @param out_distance Distance from target (or NULL to skip)
 */
ARCH_API void arch_get_camera_state(float* out_target_x, float* out_target_y, float* out_target_z, float* out_distance);

/**
 * Set camera field of view.
 *
 * @param fov Field of view in degrees (default 45)
 */
ARCH_API void arch_set_camera_fov(float fov);

/**
 * Get current camera field of view.
 *
 * @return FOV in degrees
 */
ARCH_API float arch_get_camera_fov(void);

/**
 * Set orthographic projection mode.
 *
 * @param enabled 1 for orthographic, 0 for perspective
 */
ARCH_API void arch_set_orthographic(int enabled);

/**
 * Get orthographic mode state.
 *
 * @return 1 if orthographic, 0 if perspective
 */
ARCH_API int arch_get_orthographic(void);

/**
 * Set visualization mode.
 *
 * @param mode 0=Structural, 1=Thermal, 2=Lighting, 3=Acoustic, 4=Material, 5=Wireframe
 */
ARCH_API void arch_set_viz_mode(int mode);

/**
 * Select an element by index.
 *
 * @param element_index Index of element to select, or -1 to clear
 */
ARCH_API void arch_select_element(int element_index);

/**
 * Get the currently selected element index.
 *
 * @return Selected element index, or -1 if none selected
 */
ARCH_API int arch_get_selected_element(void);

/**
 * Pick an element at screen coordinates.
 * Uses ray casting from the camera through the given screen position.
 *
 * @param screen_x X coordinate in screen pixels (0 = left)
 * @param screen_y Y coordinate in screen pixels (0 = top)
 * @return Element index at that position, or -1 if no hit
 */
ARCH_API int arch_pick_element(int screen_x, int screen_y);

/**
 * Get the number of elements in the current building.
 *
 * @return Number of elements
 */
ARCH_API int arch_get_element_count(void);

/**
 * Get last error message.
 *
 * @return Pointer to error string (valid until next API call)
 */
ARCH_API const char* arch_get_error(void);

// =============================================================================
// Section Clipping API
// =============================================================================

/**
 * Enable or disable section clipping.
 *
 * @param enabled 1 to enable, 0 to disable
 */
ARCH_API void arch_set_clipping_enabled(int enabled);

/**
 * Get current clipping state.
 *
 * @return 1 if enabled, 0 if disabled
 */
ARCH_API int arch_get_clipping_enabled(void);

/**
 * Set the clipping axis.
 *
 * @param axis 0=X (left/right), 1=Y (up/down), 2=Z (front/back)
 */
ARCH_API void arch_set_clip_axis(int axis);

/**
 * Get the current clipping axis.
 *
 * @return Current axis (0=X, 1=Y, 2=Z)
 */
ARCH_API int arch_get_clip_axis(void);

/**
 * Set the clipping plane position along the current axis.
 *
 * @param height Position in feet
 */
ARCH_API void arch_set_clip_height(float height);

/**
 * Get the current clipping height.
 *
 * @return Current height in feet
 */
ARCH_API float arch_get_clip_height(void);

/**
 * Flip the clipping direction.
 *
 * @param flipped 1 to flip, 0 for normal
 */
ARCH_API void arch_set_clip_flipped(int flipped);

/**
 * Get the current flip state.
 *
 * @return 1 if flipped, 0 if normal
 */
ARCH_API int arch_get_clip_flipped(void);

/**
 * Quick preset: Floor plan section at specified Y height.
 * Enables clipping, sets Y axis, sets height.
 *
 * @param y_height Height in feet (e.g., 4.0 for typical floor plan)
 */
ARCH_API void arch_set_section_floor_plan(float y_height);

/**
 * Quick preset: Elevation/section cut.
 * Enables clipping on X or Z axis.
 *
 * @param axis 0=X (section looking east/west), 2=Z (section looking north/south)
 * @param position Position along axis in feet
 */
ARCH_API void arch_set_section_elevation(int axis, float position);

// =============================================================================
// Section Box API (Multi-Plane Clipping)
// =============================================================================

/**
 * Set a section box to isolate a 3D region of the model.
 * Uses 6 clip planes to show only geometry within the specified bounds.
 *
 * @param min_x Minimum X bound in feet
 * @param min_y Minimum Y bound in feet
 * @param min_z Minimum Z bound in feet
 * @param max_x Maximum X bound in feet
 * @param max_y Maximum Y bound in feet
 * @param max_z Maximum Z bound in feet
 */
ARCH_API void arch_set_section_box(float min_x, float min_y, float min_z,
                                   float max_x, float max_y, float max_z);

/**
 * Clear the section box (disable all clip planes).
 */
ARCH_API void arch_clear_section_box(void);

/**
 * Check if a section box is currently active.
 *
 * @return 1 if section box is active, 0 otherwise
 */
ARCH_API int arch_has_section_box(void);

/**
 * Get the current section box bounds.
 *
 * @param out_min_x Output: minimum X
 * @param out_min_y Output: minimum Y
 * @param out_min_z Output: minimum Z
 * @param out_max_x Output: maximum X
 * @param out_max_y Output: maximum Y
 * @param out_max_z Output: maximum Z
 * @return 0 on success, non-zero if no section box is active
 */
ARCH_API int arch_get_section_box(float* out_min_x, float* out_min_y, float* out_min_z,
                                  float* out_max_x, float* out_max_y, float* out_max_z);

/**
 * Set a specific clip plane directly.
 * Advanced API for custom clipping configurations.
 *
 * @param index Plane index (0-5)
 * @param a Plane normal X component
 * @param b Plane normal Y component
 * @param c Plane normal Z component
 * @param d Plane distance from origin
 * @param enabled 1 to enable, 0 to disable
 */
ARCH_API void arch_set_clip_plane_at(int index, float a, float b, float c, float d, int enabled);

/**
 * Get a specific clip plane.
 *
 * @param index Plane index (0-5)
 * @param out_a Output: normal X
 * @param out_b Output: normal Y
 * @param out_c Output: normal Z
 * @param out_d Output: distance
 * @return 1 if plane is enabled, 0 if disabled or invalid index
 */
ARCH_API int arch_get_clip_plane_at(int index, float* out_a, float* out_b, float* out_c, float* out_d);

/**
 * Get number of active clip planes.
 *
 * @return Number of active planes (0-6)
 */
ARCH_API int arch_get_num_clip_planes(void);

// =============================================================================
// Material Style API
// =============================================================================

/**
 * Set the material rendering style.
 *
 * @param style 0=Realistic (full PBR), 1=Clean (matte), 2=Schematic (flat), 3=Blueprint
 */
ARCH_API void arch_set_material_style(int style);

/**
 * Get the current material style.
 *
 * @return Current style (0-3)
 */
ARCH_API int arch_get_material_style(void);

/**
 * Set global UV/texture scale (tiling factor).
 *
 * @param scale_u Horizontal tiling (1.0 = original size, 2.0 = 2x tiling)
 * @param scale_v Vertical tiling (1.0 = original size, 2.0 = 2x tiling)
 */
ARCH_API void arch_set_uv_scale(float scale_u, float scale_v);

/**
 * Get current UV scale.
 *
 * @param out_u Pointer to store U scale
 * @param out_v Pointer to store V scale
 */
ARCH_API void arch_get_uv_scale(float* out_u, float* out_v);

/**
 * Set roughness multiplier (affects all materials).
 *
 * @param multiplier Roughness multiplier (1.0 = default, 0.5 = smoother, 2.0 = rougher)
 */
ARCH_API void arch_set_roughness_multiplier(float multiplier);

/**
 * Get roughness multiplier.
 *
 * @return Current roughness multiplier
 */
ARCH_API float arch_get_roughness_multiplier(void);

/**
 * Set metallic multiplier (affects all materials).
 *
 * @param multiplier Metallic multiplier (1.0 = default)
 */
ARCH_API void arch_set_metallic_multiplier(float multiplier);

/**
 * Get metallic multiplier.
 *
 * @return Current metallic multiplier
 */
ARCH_API float arch_get_metallic_multiplier(void);

/**
 * Set ambient occlusion strength.
 *
 * @param strength AO strength (1.0 = full, 0.0 = none)
 */
ARCH_API void arch_set_ao_strength(float strength);

/**
 * Get ambient occlusion strength.
 *
 * @return Current AO strength
 */
ARCH_API float arch_get_ao_strength(void);

// =============================================================================
// Shadows & Lighting API
// =============================================================================

/**
 * Enable or disable shadow mapping.
 *
 * @param enabled 1 to enable, 0 to disable
 */
ARCH_API void arch_set_shadows_enabled(int enabled);

/**
 * Get shadow state.
 *
 * @return 1 if enabled, 0 if disabled
 */
ARCH_API int arch_get_shadows_enabled(void);

/**
 * Set the sun/light direction.
 *
 * @param x Direction X component
 * @param y Direction Y component (negative = down)
 * @param z Direction Z component
 */
ARCH_API void arch_set_light_direction(float x, float y, float z);

/**
 * Get current light direction.
 *
 * @param out_x Pointer to store X
 * @param out_y Pointer to store Y
 * @param out_z Pointer to store Z
 */
ARCH_API void arch_get_light_direction(float* out_x, float* out_y, float* out_z);

// =============================================================================
// SSAO (Screen Space Ambient Occlusion) API
// =============================================================================

/**
 * Enable or disable SSAO.
 *
 * @param enabled 1 to enable, 0 to disable
 */
ARCH_API void arch_set_ssao_enabled(int enabled);

/**
 * Get SSAO state.
 *
 * @return 1 if enabled, 0 if disabled
 */
ARCH_API int arch_get_ssao_enabled(void);

/**
 * Set SSAO sample radius.
 *
 * @param radius Radius in world units (default ~0.5)
 */
ARCH_API void arch_set_ssao_radius(float radius);

/**
 * Get SSAO radius.
 *
 * @return Current radius
 */
ARCH_API float arch_get_ssao_radius(void);

/**
 * Set SSAO intensity/strength.
 *
 * @param intensity Intensity multiplier (default 1.0)
 */
ARCH_API void arch_set_ssao_intensity(float intensity);

/**
 * Get SSAO intensity.
 *
 * @return Current intensity
 */
ARCH_API float arch_get_ssao_intensity(void);

// =============================================================================
// Bloom API
// =============================================================================

/**
 * Enable or disable bloom effect.
 *
 * @param enabled 1 to enable, 0 to disable
 */
ARCH_API void arch_set_bloom_enabled(int enabled);

/**
 * Get bloom state.
 *
 * @return 1 if enabled, 0 if disabled
 */
ARCH_API int arch_get_bloom_enabled(void);

/**
 * Set bloom brightness threshold.
 *
 * @param threshold Minimum brightness for bloom (default ~1.0)
 */
ARCH_API void arch_set_bloom_threshold(float threshold);

/**
 * Get bloom threshold.
 *
 * @return Current threshold
 */
ARCH_API float arch_get_bloom_threshold(void);

/**
 * Set bloom intensity.
 *
 * @param intensity Bloom strength (default ~0.5)
 */
ARCH_API void arch_set_bloom_intensity(float intensity);

/**
 * Get bloom intensity.
 *
 * @return Current intensity
 */
ARCH_API float arch_get_bloom_intensity(void);

// =============================================================================
// Tonemapping & Exposure API
// =============================================================================

/**
 * Set camera exposure.
 *
 * @param exposure Exposure value (default 1.0)
 */
ARCH_API void arch_set_exposure(float exposure);

/**
 * Get current exposure.
 *
 * @return Current exposure
 */
ARCH_API float arch_get_exposure(void);

/**
 * Set tonemapping operator.
 *
 * @param mode 0=Reinhard, 1=ACES, 2=Uncharted2
 */
ARCH_API void arch_set_tonemap_mode(int mode);

/**
 * Get current tonemap mode.
 *
 * @return Current mode (0-2)
 */
ARCH_API int arch_get_tonemap_mode(void);

// =============================================================================
// Room Data Export API
// =============================================================================

/**
 * Room data structure for export to Python.
 * All coordinates in mm.
 */
typedef struct {
    char id[64];           // Room ID
    char name[128];        // Room name
    char room_type[64];    // Room type (bedroom, kitchen, etc.)
    float bounds_x;        // Bounding box X
    float bounds_y;        // Bounding box Y
    float bounds_width;    // Bounding box width
    float bounds_height;   // Bounding box height
    float center_x;        // Center X
    float center_y;        // Center Y (actually Z in 3D)
    float area;            // Area in sq ft
    int zone;              // Zone (0=Public, 1=Private, 2=Service, 3=Circulation)
} ArchRoomData;

/**
 * Get the number of rooms in the current layout.
 *
 * @return Number of rooms
 */
ARCH_API int arch_get_room_count(void);

/**
 * Get room data by index.
 *
 * @param index Room index (0 to room_count-1)
 * @param out_room Pointer to room data struct to fill
 * @return 0 on success, non-zero if index out of bounds
 */
ARCH_API int arch_get_room_data(int index, ArchRoomData* out_room);

/**
 * Get all room data at once.
 *
 * @param out_rooms Array to fill (must have space for room_count rooms)
 * @param max_rooms Maximum rooms to return
 * @return Number of rooms filled
 */
ARCH_API int arch_get_all_rooms(ArchRoomData* out_rooms, int max_rooms);

// =============================================================================
// Per-Element Material Override API
// ============================================================================

/**
 * Set material override for a specific element.
 * Allows individual walls/elements to have different material properties.
 *
 * @param element_index Index of element to modify
 * @param uv_scale UV scale multiplier (1.0 = default, 2.0 = 2x denser tiling)
 * @param normal_strength Normal map intensity (1.0 = default, 2.0 = stronger normals)
 * @param brightness Brightness adjustment (0.0 = default, positive = brighter)
 * @param contrast Contrast adjustment (1.0 = default, >1 = higher contrast)
 * @return 0 on success, non-zero on failure (invalid element index)
 */
ARCH_API int arch_set_element_material(int element_index,
                                       float uv_scale,
                                       float normal_strength,
                                       float brightness,
                                       float contrast);

/**
 * Clear material override for a specific element.
 * Element will revert to using global material settings.
 *
 * @param element_index Index of element to clear
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_clear_element_material(int element_index);

/**
 * Clear all material overrides.
 * All elements will revert to global material settings.
 */
ARCH_API void arch_clear_all_material_overrides(void);

/**
 * Check if element has a material override.
 *
 * @param element_index Index of element to check
 * @return 1 if element has override, 0 otherwise
 */
ARCH_API int arch_has_material_override(int element_index);

/**
 * Get material override values for an element.
 *
 * @param element_index Index of element to query
 * @param out_uv_scale Output: UV scale (or 0 if no override)
 * @param out_normal_strength Output: Normal strength (or 0 if no override)
 * @param out_brightness Output: Brightness (or 0 if no override)
 * @param out_contrast Output: Contrast (or 0 if no override)
 * @return 0 on success, non-zero if element has no override or invalid index
 */
ARCH_API int arch_get_element_material(int element_index,
                                      float* out_uv_scale,
                                      float* out_normal_strength,
                                      float* out_brightness,
                                      float* out_contrast);

/**
 * Apply material override to multiple elements at once.
 * Useful for batch operations (e.g., select all walls and adjust together).
 *
 * @param indices Array of element indices
 * @param count Number of elements in array
 * @param uv_scale UV scale multiplier
 * @param normal_strength Normal map intensity
 * @param brightness Brightness adjustment
 * @param contrast Contrast adjustment
 * @return Number of elements successfully updated
 */
ARCH_API int arch_apply_material_batch(const int* indices, int count,
                                       float uv_scale,
                                       float normal_strength,
                                       float brightness,
                                       float contrast);

/**
 * Get the number of elements with material overrides.
 *
 * @return Count of elements with active overrides
 */
ARCH_API int arch_get_override_count(void);

/**
 * Get indices of all elements with material overrides.
 *
 * @param out_indices Output array (must be large enough)
 * @param max_indices Maximum number of indices to retrieve
 * @return Number of indices actually retrieved
 */
ARCH_API int arch_get_override_indices(int* out_indices, int max_indices);

// =============================================================================
// Material Library API
// =============================================================================

/**
 * Get the number of available materials.
 *
 * @return Number of materials in the library
 */
ARCH_API int arch_get_material_count(void);

/**
 * Get material name by index.
 *
 * @param index Material index (0 to material_count-1)
 * @return Material name (valid until next API call), or NULL if invalid index
 */
ARCH_API const char* arch_get_material_name(int index);

/**
 * Get material category/path.
 * Examples: "walls", "floors", "roofs", "windows", "doors"
 *
 * @param index Material index
 * @return Category string (valid until next API call), or NULL if invalid
 */
ARCH_API const char* arch_get_material_category(int index);

/**
 * Get all materials in a specific category.
 *
 * @param category Category filter (e.g., "walls", "floors")
 * @param out_indices Output array for material indices
 * @param max_indices Maximum number of indices to retrieve
 * @return Number of materials found in category
 */
ARCH_API int arch_get_materials_by_category(const char* category,
                                            int* out_indices,
                                            int max_indices);

/**
 * Find material index by name.
 *
 * @param name Material name to search for
 * @return Material index, or -1 if not found
 */
ARCH_API int arch_find_material(const char* name);

/**
 * Apply a material to an element.
 *
 * @param element_index Index of element to modify
 * @param material_name Name of material to apply
 * @return 0 on success, non-zero on failure (invalid index or material not found)
 */
ARCH_API int arch_apply_material_to_element(int element_index, const char* material_name);

/**
 * Apply a material to multiple elements at once.
 *
 * @param indices Array of element indices
 * @param count Number of elements
 * @param material_name Name of material to apply
 * @return Number of elements successfully updated
 */
ARCH_API int arch_apply_material_to_batch(const int* indices, int count, const char* material_name);

/**
 * Get the material currently applied to an element.
 *
 * @param element_index Index of element to query
 * @param out_name Output buffer for material name
 * @param max_length Maximum length of output buffer
 * @return 0 on success, non-zero on failure (no material or invalid index)
 */
ARCH_API int arch_get_element_material_name(int element_index, char* out_name, int max_length);

// =============================================================================
// Material Preview API
// =============================================================================

/**
 * Material preview handle.
 * Returned by arch_create_material_preview(), used by arch_get_preview_pixels().
 */
typedef void* ArchPreviewHandle;

/**
 * Create a material preview render.
 * Renders the specified material to an offscreen texture.
 *
 * @param material_name Name of material to preview
 * @param width Preview width in pixels (recommended: 128, 256, 512)
 * @param height Preview height in pixels
 * @return Preview handle, or NULL on failure
 */
ARCH_API ArchPreviewHandle arch_create_material_preview(const char* material_name,
                                                       int width, int height);

/**
 * Destroy a material preview and release resources.
 *
 * @param preview Preview handle to destroy
 */
ARCH_API void arch_destroy_material_preview(ArchPreviewHandle preview);

/**
 * Get preview image pixels.
 * Returns RGBA8 data (4 bytes per pixel).
 *
 * @param preview Preview handle
 * @param out_pixels Output buffer (must be width * height * 4 bytes)
 * @param buffer_size Size of output buffer
 * @return 0 on success, non-zero on failure (buffer too small or invalid handle)
 */
ARCH_API int arch_get_preview_pixels(ArchPreviewHandle preview,
                                     unsigned char* out_pixels,
                                     int buffer_size);

/**
 * Get preview dimensions.
 *
 * @param preview Preview handle
 * @param out_width Output: width in pixels
 * @param out_height Output: height in pixels
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_get_preview_size(ArchPreviewHandle preview, int* out_width, int* out_height);

// =============================================================================
// Terrain Mesh API
// =============================================================================

/**
 * Terrain vertex structure for direct data upload.
 * Position in feet (will be converted to mm internally).
 */
typedef struct {
    float pos_x, pos_y, pos_z;    // Position in feet (x=east, y=up/elevation, z=north)
    float normal_x, normal_y, normal_z;  // Surface normal
    float u, v;                   // UV coordinates (0-1)
} ArchTerrainVertex;

/**
 * Set terrain mesh data directly.
 * This allows Python to generate terrain data and upload it without JSON.
 *
 * Positions are expected in feet and will be converted to millimeters internally.
 * Vertex colors are computed automatically from elevation (Y coordinate).
 *
 * @param vertices Array of terrain vertices
 * @param vertex_count Number of vertices
 * @param indices Array of triangle indices (3 per triangle)
 * @param index_count Number of indices
 * @param width_ft Terrain width in feet (X dimension)
 * @param depth_ft Terrain depth in feet (Z dimension)
 * @param min_elevation Minimum elevation in feet
 * @param max_elevation Maximum elevation in feet
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_set_terrain_data(const ArchTerrainVertex* vertices, int vertex_count,
                                   const unsigned int* indices, int index_count,
                                   float width_ft, float depth_ft,
                                   float min_elevation, float max_elevation);

/**
 * Clear terrain mesh data.
 * Removes any loaded terrain from the scene.
 */
ARCH_API void arch_clear_terrain(void);

/**
 * Check if terrain data is loaded.
 *
 * @return 1 if terrain exists, 0 otherwise
 */
ARCH_API int arch_has_terrain(void);

/**
 * Get terrain information.
 *
 * @param out_width_ft Output: terrain width in feet (or NULL to skip)
 * @param out_depth_ft Output: terrain depth in feet (or NULL to skip)
 * @param out_min_elev Output: minimum elevation in feet (or NULL to skip)
 * @param out_max_elev Output: maximum elevation in feet (or NULL to skip)
 * @param out_vertex_count Output: number of vertices (or NULL to skip)
 * @param out_triangle_count Output: number of triangles (or NULL to skip)
 * @return 0 on success, -1 if no terrain loaded
 */
ARCH_API int arch_get_terrain_info(float* out_width_ft, float* out_depth_ft,
                                   float* out_min_elev, float* out_max_elev,
                                   int* out_vertex_count, int* out_triangle_count);

/**
 * Set terrain visibility.
 *
 * @param enabled 1 to show terrain, 0 to hide
 */
ARCH_API void arch_set_terrain_enabled(int enabled);

/**
 * Get terrain visibility state.
 *
 * @return 1 if enabled, 0 if disabled
 */
ARCH_API int arch_get_terrain_enabled(void);

/**
 * Set terrain position offset.
 * Useful for centering terrain under a building.
 *
 * @param offset_x X offset in feet
 * @param offset_y Y offset in feet (vertical)
 * @param offset_z Z offset in feet
 */
ARCH_API void arch_set_terrain_offset(float offset_x, float offset_y, float offset_z);

/**
 * Get terrain position offset.
 *
 * @param out_x Output: X offset in feet
 * @param out_y Output: Y offset in feet
 * @param out_z Output: Z offset in feet
 */
ARCH_API void arch_get_terrain_offset(float* out_x, float* out_y, float* out_z);

/**
 * Set terrain material properties.
 *
 * @param roughness Surface roughness (0.0-1.0, default 0.8)
 * @param metallic Surface metallic value (0.0-1.0, default 0.0)
 */
ARCH_API void arch_set_terrain_material(float roughness, float metallic);

/**
 * Set terrain color mode.
 *
 * @param mode 0=Elevation gradient (default), 1=Uniform gray, 2=Satellite texture (future)
 */
ARCH_API void arch_set_terrain_color_mode(int mode);

/**
 * Elevation point for terrain generation.
 * Coordinates in WGS84 (lat/lng) with elevation in meters.
 */
typedef struct {
    float lat;          // Latitude (degrees)
    float lng;          // Longitude (degrees)
    float elevation_m;  // Elevation in meters above sea level
} ArchElevationPoint;

/**
 * Generate terrain mesh from raw elevation points.
 *
 * This performs high-performance mesh generation in C++ from LiDAR or other
 * elevation data. Much faster than Python-based generation.
 *
 * The function:
 * 1. Creates a grid within the polygon boundary
 * 2. Interpolates elevation at each grid point from nearby samples
 * 3. Generates triangulated mesh with normals and UVs
 * 4. Stores result internally (replaces any existing terrain)
 *
 * @param points Array of elevation points (lat, lng, elevation_m)
 * @param point_count Number of elevation points
 * @param boundary_ft Polygon boundary vertices in feet [x0,z0, x1,z1, ...]
 *                    relative to property corner. NULL for rectangular bounds.
 * @param boundary_vertex_count Number of boundary vertices (0 if NULL boundary)
 * @param bounds_lat_min Minimum latitude of data bounds
 * @param bounds_lat_max Maximum latitude of data bounds
 * @param bounds_lng_min Minimum longitude of data bounds
 * @param bounds_lng_max Maximum longitude of data bounds
 * @param width_ft Property width in feet
 * @param depth_ft Property depth in feet
 * @param grid_resolution Mesh resolution (100=20k tris, 300=180k, 500=500k)
 * @param origin_x_ft Building origin X offset in feet (terrain shifted so building at 0,0)
 * @param origin_z_ft Building origin Z offset in feet
 * @param rotation_deg Building rotation in degrees (terrain rotated to match)
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_generate_terrain_from_points(
    const ArchElevationPoint* points,
    int point_count,
    const float* boundary_ft,
    int boundary_vertex_count,
    float bounds_lat_min, float bounds_lat_max,
    float bounds_lng_min, float bounds_lng_max,
    float width_ft, float depth_ft,
    int grid_resolution,
    float origin_x_ft, float origin_z_ft,
    float rotation_deg
);

/**
 * Get terrain generation progress (for async generation).
 *
 * @param out_progress Output: progress 0.0-1.0 (or NULL to skip)
 * @param out_status Output: status string (or NULL to skip)
 * @return 1 if generation in progress, 0 if complete or not started
 */
ARCH_API int arch_get_terrain_generation_progress(float* out_progress, const char** out_status);

// =============================================================================
// Environment/HDRI API
// =============================================================================

/**
 * Load an HDR environment map for IBL lighting.
 * Supports .hdr files (Radiance HDR format).
 *
 * @param path Path to the .hdr file
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_load_hdri(const char* path);

/**
 * List available HDRI files in the hdri directory.
 *
 * @return Semicolon-separated list of .hdr filenames, or empty string if none found
 */
ARCH_API const char* arch_list_hdris(void);

// =============================================================================
// Path Tracer API (Offline Rendering for V-Ray Quality Stills)
// =============================================================================

/**
 * Configure path tracer parameters.
 * Must be called before arch_pt_start_render().
 *
 * @param width Output image width in pixels
 * @param height Output image height in pixels
 * @param samples Total samples per pixel (higher = less noise, longer render)
 * @param bounces Maximum path bounces (higher = more accurate GI)
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_pt_set_config(int width, int height, int samples, int bounces);

/**
 * Start path traced render.
 * Begins progressive rendering of the current scene.
 * Call arch_pt_render_frame() repeatedly until done.
 *
 * @return 0 on success, non-zero on failure (e.g., no scene loaded)
 */
ARCH_API int arch_pt_start_render(void);

/**
 * Render one progressive frame.
 * Each call adds samples to the accumulation buffer.
 *
 * @return 1 if more frames needed, 0 if complete, -1 on error
 */
ARCH_API int arch_pt_render_frame(void);

/**
 * Get render progress.
 *
 * @param progress Output: progress value from 0.0 to 1.0
 * @return 0 on success
 */
ARCH_API int arch_pt_get_progress(float* progress);

/**
 * Stop the current render early.
 * Can be used to cancel a long render.
 */
ARCH_API void arch_pt_stop(void);

/**
 * Check if path tracer is currently rendering.
 *
 * @return 1 if rendering, 0 if idle or complete
 */
ARCH_API int arch_pt_is_rendering(void);

/**
 * Check if render is complete.
 *
 * @return 1 if complete, 0 if not started or still rendering
 */
ARCH_API int arch_pt_is_complete(void);

/**
 * Get current sample count.
 *
 * @return Number of samples completed
 */
ARCH_API int arch_pt_get_sample_count(void);

/**
 * Save path traced result as PNG.
 * Applies tonemapping and gamma correction.
 *
 * @param path Output file path
 * @param exposure Exposure adjustment (1.0 = default)
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_pt_save_png(const char* path, float exposure);

/**
 * Save path traced result as HDR (Radiance format).
 * Preserves full dynamic range for post-processing.
 *
 * @param path Output file path (will use .hdr extension)
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_pt_save_hdr(const char* path);

/**
 * Apply denoising to the path traced result.
 * Uses edge-aware spatial filtering to reduce noise.
 *
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_pt_apply_denoise(void);

/**
 * Set path tracer exposure.
 *
 * @param exposure Exposure value (default 1.0)
 */
ARCH_API void arch_pt_set_exposure(float exposure);

/**
 * Get path tracer exposure.
 *
 * @return Current exposure value
 */
ARCH_API float arch_pt_get_exposure(void);

/**
 * Set path tracer tonemapping mode.
 *
 * @param mode 0=Reinhard, 1=ACES (default), 2=Uncharted2
 */
ARCH_API void arch_pt_set_tonemap_mode(int mode);

/**
 * Get path tracer tonemapping mode.
 *
 * @return Current tonemap mode (0-2)
 */
ARCH_API int arch_pt_get_tonemap_mode(void);

/**
 * Enable or disable Next Event Estimation (direct light sampling).
 * NEE significantly reduces noise for direct lighting.
 *
 * @param enabled 1 to enable (default), 0 to disable
 */
ARCH_API void arch_pt_set_nee_enabled(int enabled);

/**
 * Enable or disable Russian Roulette path termination.
 * RR improves efficiency by probabilistically terminating low-contribution paths.
 *
 * @param enabled 1 to enable (default), 0 to disable
 */
ARCH_API void arch_pt_set_rr_enabled(int enabled);

// =============================================================================
// Tessellation API
// =============================================================================

/**
 * Enable or disable hardware tessellation for displacement mapping.
 * When enabled, surfaces are subdivided and displaced by height maps.
 *
 * @param enabled 1 to enable, 0 to disable (default)
 */
ARCH_API void arch_set_tessellation_enabled(int enabled);

/**
 * Check if tessellation is enabled.
 *
 * @return 1 if enabled, 0 if disabled
 */
ARCH_API int arch_get_tessellation_enabled(void);

/**
 * Set tessellation subdivision level.
 *
 * @param level Subdivision level (1.0 = no subdivision, 64.0 = max)
 */
ARCH_API void arch_set_tessellation_level(float level);

/**
 * Get tessellation subdivision level.
 *
 * @return Current tessellation level
 */
ARCH_API float arch_get_tessellation_level(void);

/**
 * Set displacement scale for tessellated surfaces.
 *
 * @param scale Displacement scale in scene units (0.0 = no displacement)
 */
ARCH_API void arch_set_displacement_scale(float scale);

/**
 * Get displacement scale.
 *
 * @return Current displacement scale
 */
ARCH_API float arch_get_displacement_scale(void);

// =============================================================================
// LOD (Level of Detail) API
// =============================================================================

/**
 * Set rendering LOD level.
 * Adjusts tessellation, shadow quality, and other render settings based on LOD.
 *
 * LOD Levels:
 *   1 = Topology (minimal detail, fastest rendering)
 *   2 = Spatial (low detail, good for interactive editing)
 *   3 = Assembly (medium detail, balanced quality)
 *   4 = Construction (high detail, production quality)
 *   5 = Fabrication (maximum detail, final renders)
 *
 * @param level LOD level (1-5)
 */
ARCH_API void arch_set_lod_level(int level);

/**
 * Get current LOD level.
 *
 * @return Current LOD level (1-5)
 */
ARCH_API int arch_get_lod_level(void);

// =============================================================================
// Frame Capture API
// =============================================================================

/**
 * Capture the current frame to a PNG file.
 *
 * Renders a single frame and saves it to the specified path.
 * Useful for generating elevation views, thumbnails, or documentation.
 *
 * @param path Output file path (must end in .png)
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_capture_frame(const char* path);

/**
 * Capture an orthogonal view for elevation/section generation.
 *
 * Temporarily switches to orthographic mode, sets camera to specified direction,
 * captures the frame, then restores previous camera state.
 *
 * @param path Output file path
 * @param direction View direction: 0=South, 1=North, 2=East, 3=West
 * @param section_enabled 1 to enable section cut, 0 for full view
 * @param section_depth Section cut depth in feet (only used if section_enabled)
 * @return 0 on success, non-zero on failure
 */
ARCH_API int arch_capture_elevation(const char* path, int direction, int section_enabled, float section_depth);

#ifdef __cplusplus
}
#endif

#endif /* ARCH_API_H */
