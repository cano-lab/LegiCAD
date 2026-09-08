#pragma once

#include "types.hpp"

namespace arch {

/**
 * @brief Light group categories for organizing scene lighting
 */
enum class LightGroup : u32 {
    Interior = 0,   // Indoor lights (rooms, hallways)
    Exterior = 1,   // Outdoor lights (sun, street lights)
    Accent = 2,     // Decorative/highlight lights
    Custom = 3      // User-defined group
};

/**
 * @brief Light wrapper with convenient helper methods
 *
 * Extends GPULight (defined in types.hpp) with factory methods and getters/setters.
 * The underlying data layout matches the GPU struct exactly for direct UBO transfer.
 * Additional CPU-only fields (group, enabled) are stored separately.
 */
struct Light : public GPULight {
    // CPU-only fields (not sent to GPU)
    LightGroup group = LightGroup::Interior;
    bool enabled = true;
    bool castShadow = false;  // Whether this light casts shadows
    /**
     * @brief Create a point light
     * @param position World position of the light
     * @param color RGB color (0-1 range, can exceed for HDR)
     * @param intensity Light intensity multiplier
     * @param range Maximum range of the light
     */
    static Light createPoint(vec3 position, vec3 color, f32 intensity, f32 range) {
        Light light{};
        light.positionType = vec4(position, static_cast<f32>(LightType::Point));
        light.directionRange = vec4(0.0f, -1.0f, 0.0f, range);
        light.colorIntensity = vec4(color, intensity);
        light.spotParams = vec4(0.0f, 0.0f, -1.0f, 0.0f);
        return light;
    }

    /**
     * @brief Create a spot light
     * @param position World position of the light
     * @param direction Direction the light points
     * @param color RGB color
     * @param intensity Light intensity multiplier
     * @param range Maximum range
     * @param innerAngleDeg Inner cone angle in degrees (full brightness)
     * @param outerAngleDeg Outer cone angle in degrees (falloff to zero)
     */
    static Light createSpot(vec3 position, vec3 direction, vec3 color, f32 intensity,
                            f32 range, f32 innerAngleDeg, f32 outerAngleDeg) {
        Light light{};
        light.positionType = vec4(position, static_cast<f32>(LightType::Spot));
        light.directionRange = vec4(glm::normalize(direction), range);
        light.colorIntensity = vec4(color, intensity);
        // Store cosines for efficient GPU calculation
        light.spotParams = vec4(
            glm::cos(glm::radians(innerAngleDeg)),
            glm::cos(glm::radians(outerAngleDeg)),
            -1.0f,  // No shadow by default
            0.0f
        );
        return light;
    }

    /**
     * @brief Create a directional light (like sun/moon)
     * @param direction Direction from light to scene (normalized)
     * @param color RGB color
     * @param intensity Light intensity multiplier
     */
    static Light createDirectional(vec3 direction, vec3 color, f32 intensity) {
        Light light{};
        light.positionType = vec4(0.0f, 0.0f, 0.0f, static_cast<f32>(LightType::Directional));
        light.directionRange = vec4(glm::normalize(direction), 0.0f);
        light.colorIntensity = vec4(color, intensity);
        light.spotParams = vec4(0.0f, 0.0f, -1.0f, 0.0f);
        return light;
    }

    // Getters for convenience
    LightType getType() const { return static_cast<LightType>(static_cast<u32>(positionType.w)); }
    vec3 getPosition() const { return vec3(positionType); }
    vec3 getDirection() const { return vec3(directionRange); }
    f32 getRange() const { return directionRange.w; }
    vec3 getColor() const { return vec3(colorIntensity); }
    f32 getIntensity() const { return colorIntensity.a; }
    f32 getInnerAngleCos() const { return spotParams.x; }
    f32 getOuterAngleCos() const { return spotParams.y; }
    i32 getShadowIndex() const { return static_cast<i32>(spotParams.z); }

    // Setters
    void setPosition(vec3 pos) { positionType = vec4(pos, positionType.w); }
    void setDirection(vec3 dir) { directionRange = vec4(glm::normalize(dir), directionRange.w); }
    void setRange(f32 range) { directionRange.w = range; }
    void setColor(vec3 color) { colorIntensity = vec4(color, colorIntensity.a); }
    void setIntensity(f32 intensity) { colorIntensity.a = intensity; }
    void setSpotAngles(f32 innerDeg, f32 outerDeg) {
        spotParams.x = glm::cos(glm::radians(innerDeg));
        spotParams.y = glm::cos(glm::radians(outerDeg));
    }
    void setShadowIndex(i32 idx) { spotParams.z = static_cast<f32>(idx); }

    // Get inner/outer angles in degrees (for UI)
    f32 getInnerAngleDeg() const { return glm::degrees(glm::acos(spotParams.x)); }
    f32 getOuterAngleDeg() const { return glm::degrees(glm::acos(spotParams.y)); }

    // Group management
    LightGroup getGroup() const { return group; }
    void setGroup(LightGroup g) { group = g; }
    bool isEnabled() const { return enabled; }
    void setEnabled(bool e) { enabled = e; }
    bool isCastingShadow() const { return castShadow; }
    void setCastShadow(bool cast) { castShadow = cast; }
};

/**
 * @brief Light preset configurations for common scenarios
 */
namespace LightPresets {
    /// Warm interior light (incandescent bulb)
    inline Light WarmInterior(vec3 position, f32 range = 10.0f) {
        return Light::createPoint(position, vec3(1.0f, 0.85f, 0.7f), 2.0f, range);
    }

    /// Cool white light (LED/fluorescent)
    inline Light CoolWhite(vec3 position, f32 range = 10.0f) {
        return Light::createPoint(position, vec3(0.95f, 0.98f, 1.0f), 2.5f, range);
    }

    /// Candle/fire light
    inline Light Candle(vec3 position, f32 range = 3.0f) {
        return Light::createPoint(position, vec3(1.0f, 0.6f, 0.2f), 1.0f, range);
    }

    /// Spotlight for accent lighting
    inline Light AccentSpot(vec3 position, vec3 direction, f32 range = 15.0f) {
        return Light::createSpot(position, direction, vec3(1.0f), 5.0f, range, 15.0f, 25.0f);
    }

    /// Construction work light (bright, harsh)
    inline Light WorkLight(vec3 position, f32 range = 20.0f) {
        return Light::createPoint(position, vec3(1.0f, 0.98f, 0.92f), 10.0f, range);
    }

    /// Outdoor streetlight (sodium vapor)
    inline Light StreetLight(vec3 position, vec3 direction, f32 range = 25.0f) {
        return Light::createSpot(position, direction, vec3(1.0f, 0.78f, 0.44f), 8.0f, range, 45.0f, 60.0f);
    }

    /// Daylight simulation (cool sunlight)
    inline Light Daylight(vec3 position, f32 range = 50.0f) {
        return Light::createPoint(position, vec3(1.0f, 0.98f, 0.95f), 5.0f, range);
    }

    /// Architectural recessed downlight
    inline Light RecessedDownlight(vec3 position, f32 range = 8.0f) {
        return Light::createSpot(position, vec3(0.0f, -1.0f, 0.0f), vec3(1.0f, 0.95f, 0.9f), 3.0f, range, 30.0f, 45.0f);
    }
}

} // namespace arch
