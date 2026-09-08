//! Shared UBO — matches `shaders/include/ubo.glsl` field-for-field (which in
//! turn must match C++ `UniformBufferObject`, types.hpp:296). Consumed today
//! by `sky.vert/frag`; `structural.*` will use the rest of the fields when
//! the full material stack is ported.

use glam::{Mat4, Vec4};

pub const MAX_LIGHTS: usize = 16;
pub const MAX_SHADOW_MAPS: usize = 4;
pub const MAX_CLIP_PLANES: usize = 6;

/// Effect flags (`EffectFlags` in types.hpp).
pub const EFFECT_IBL: u32 = 1 << 0;
pub const EFFECT_DIRECT_LIGHT: u32 = 1 << 1;
pub const EFFECT_NORMAL_MAPPING: u32 = 1 << 2;

/// `GPULight` — 4×vec4, 64 bytes.
#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct GpuLight {
    /// xyz = world position, w = type.
    pub position_type: Vec4,
    /// xyz = direction, w = range.
    pub direction_range: Vec4,
    /// rgb = color, a = intensity.
    pub color_intensity: Vec4,
    /// x = innerAngle (cos), y = outerAngle (cos), z = shadowIndex, w = reserved.
    pub spot_params: Vec4,
}

const _: () = assert!(std::mem::size_of::<GpuLight>() == 64);

/// `UniformBufferObject` (std140). 1,728 bytes.
#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct SharedUbo {
    pub view: Mat4,
    pub proj: Mat4,
    pub light_view_proj: [Mat4; MAX_SHADOW_MAPS],
    /// Directional light direction (sun).
    pub light_direction: Vec4,
    /// Section clipping planes.
    pub clip_planes: [Vec4; MAX_CLIP_PLANES],
    pub time: f32,
    pub shadow_bias: f32,
    pub enable_clipping: u32,
    pub num_clip_planes: u32,
    pub enable_shadows: u32,
    /// Output linear HDR (skip tonemapping in shader).
    pub output_linear_hdr: u32,
    pub num_shadow_maps: u32,
    pub exposure: f32,
    pub tessellation_level: f32,
    pub displacement_scale: f32,
    pub pad_align1: f32,
    pub pad_align2: f32,
    /// x = UV scale, y = normal strength, z = brightness, w = contrast.
    pub material_params: Vec4,
    /// x = saturation, y = roughnessOffset, z = metallicOffset, w = aoStrength.
    pub material_params2: Vec4,
    /// RGB tint multiplier.
    pub material_tint: Vec4,
    /// x = enabled, y = heightScale, z = minLayers, w = maxLayers.
    pub pom_params: Vec4,
    /// x = overall, y = diffuse, z = specular, w = fresnel intensity.
    pub ibl_params: Vec4,
    pub material_debug_mode: u32,
    pub override_mask: u32,
    /// bit0 = IBL, bit1 = directLight, bit2 = normalMapping.
    pub effect_flags: u32,
    pub pad1: f32,
    pub element_override1: Vec4,
    pub element_override2: Vec4,
    pub element_override3: Vec4,
    pub num_lights: u32,
    pub pad3: f32,
    pub pad4: f32,
    pub pad5: f32,
    pub lights: [GpuLight; MAX_LIGHTS],
}

const _: () = assert!(std::mem::size_of::<SharedUbo>() == 1728);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn field_offsets_match_std140() {
        assert_eq!(std::mem::offset_of!(SharedUbo, view), 0);
        assert_eq!(std::mem::offset_of!(SharedUbo, proj), 64);
        assert_eq!(std::mem::offset_of!(SharedUbo, light_view_proj), 128);
        assert_eq!(std::mem::offset_of!(SharedUbo, light_direction), 384);
        assert_eq!(std::mem::offset_of!(SharedUbo, clip_planes), 400);
        assert_eq!(std::mem::offset_of!(SharedUbo, time), 496);
        assert_eq!(std::mem::offset_of!(SharedUbo, output_linear_hdr), 516);
        assert_eq!(std::mem::offset_of!(SharedUbo, material_params), 544);
        assert_eq!(std::mem::offset_of!(SharedUbo, ibl_params), 608);
        assert_eq!(std::mem::offset_of!(SharedUbo, material_debug_mode), 624);
        assert_eq!(std::mem::offset_of!(SharedUbo, element_override1), 640);
        assert_eq!(std::mem::offset_of!(SharedUbo, num_lights), 688);
        assert_eq!(std::mem::offset_of!(SharedUbo, lights), 704);
    }
}
