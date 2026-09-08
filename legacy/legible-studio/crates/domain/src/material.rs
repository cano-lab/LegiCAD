//! `MaterialPreset` + named factories — port of `types.hpp:371-411`.

use glam::Vec3;
use serde::{Deserialize, Serialize};

/// PBR material preset.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MaterialPreset {
    pub base_color: Vec3,
    pub metallic: f32,
    pub roughness: f32,
    pub ao: f32,
    pub emission: f32,
}

impl Default for MaterialPreset {
    fn default() -> Self {
        Self {
            base_color: Vec3::splat(0.8),
            metallic: 0.0,
            roughness: 0.5,
            ao: 1.0,
            emission: 0.0,
        }
    }
}

/// Named material factories. Const where possible (glam `Vec3::new` is const).
///
/// Values are the C++ `arch::Materials::*` inline factories at `types.hpp:382-410`.
pub mod materials {
    use super::MaterialPreset;
    use glam::Vec3;

    // Woods
    pub const OAK_WOOD: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.55, 0.35, 0.18),
        metallic: 0.0,
        roughness: 0.7,
        ao: 1.0,
        emission: 0.0,
    };
    pub const DARK_WOOD: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.35, 0.22, 0.12),
        metallic: 0.0,
        roughness: 0.65,
        ao: 1.0,
        emission: 0.0,
    };
    pub const PINE_WOOD: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.75, 0.6, 0.4),
        metallic: 0.0,
        roughness: 0.75,
        ao: 1.0,
        emission: 0.0,
    };

    // Metals
    pub const STEEL: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.56, 0.57, 0.58),
        metallic: 0.9,
        roughness: 0.3,
        ao: 1.0,
        emission: 0.0,
    };
    pub const ALUMINUM: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.91, 0.92, 0.92),
        metallic: 0.85,
        roughness: 0.35,
        ao: 1.0,
        emission: 0.0,
    };
    pub const BRASS: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.7, 0.55, 0.2),
        metallic: 0.8,
        roughness: 0.25,
        ao: 1.0,
        emission: 0.0,
    };
    pub const COPPER: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.72, 0.45, 0.2),
        metallic: 0.85,
        roughness: 0.25,
        ao: 1.0,
        emission: 0.0,
    };

    // Walls
    pub const DRYWALL: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.9, 0.88, 0.85),
        metallic: 0.0,
        roughness: 0.95,
        ao: 1.0,
        emission: 0.0,
    };
    pub const BRICK: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.6, 0.25, 0.15),
        metallic: 0.0,
        roughness: 0.85,
        ao: 0.9,
        emission: 0.0,
    };
    pub const CONCRETE: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.55, 0.55, 0.55),
        metallic: 0.0,
        roughness: 0.9,
        ao: 0.85,
        emission: 0.0,
    };
    pub const STUCCO: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.85, 0.82, 0.75),
        metallic: 0.0,
        roughness: 0.92,
        ao: 0.95,
        emission: 0.0,
    };

    // Glass
    pub const GLASS: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.7, 0.85, 0.95),
        metallic: 0.1,
        roughness: 0.05,
        ao: 1.0,
        emission: 0.0,
    };
    pub const TINTED_GLASS: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.3, 0.4, 0.5),
        metallic: 0.1,
        roughness: 0.08,
        ao: 1.0,
        emission: 0.0,
    };

    // Roof
    pub const ASPHALT: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.2, 0.2, 0.22),
        metallic: 0.0,
        roughness: 0.85,
        ao: 0.8,
        emission: 0.0,
    };
    pub const TERRACOTTA_TILE: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.7, 0.35, 0.2),
        metallic: 0.0,
        roughness: 0.7,
        ao: 0.9,
        emission: 0.0,
    };
    pub const METAL_ROOF: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.4, 0.42, 0.45),
        metallic: 0.7,
        roughness: 0.4,
        ao: 1.0,
        emission: 0.0,
    };

    // Floor
    pub const HARDWOOD: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.45, 0.3, 0.15),
        metallic: 0.0,
        roughness: 0.6,
        ao: 1.0,
        emission: 0.0,
    };
    pub const TILE: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.8, 0.8, 0.8),
        metallic: 0.1,
        roughness: 0.3,
        ao: 1.0,
        emission: 0.0,
    };
    pub const CARPET: MaterialPreset = MaterialPreset {
        base_color: Vec3::new(0.3, 0.35, 0.4),
        metallic: 0.0,
        roughness: 0.98,
        ao: 0.9,
        emission: 0.0,
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_matches_cpp_default() {
        // C++ default-constructed MaterialPreset: baseColor=vec3(0.8), metallic=0,
        // roughness=0.5, ao=1.0, emission=0.0.
        let m = MaterialPreset::default();
        assert_eq!(m.base_color, Vec3::splat(0.8));
        assert_eq!(m.metallic, 0.0);
        assert_eq!(m.roughness, 0.5);
        assert_eq!(m.ao, 1.0);
        assert_eq!(m.emission, 0.0);
    }

    #[test]
    fn steel_factory_matches_cpp() {
        let s = materials::STEEL;
        assert_eq!(s.base_color, Vec3::new(0.56, 0.57, 0.58));
        assert_eq!(s.metallic, 0.9);
        assert_eq!(s.roughness, 0.3);
    }

    #[test]
    fn glass_has_nonzero_metallic() {
        // Glass has metallic=0.1 in the C++ — a quirk we preserve.
        assert_eq!(materials::GLASS.metallic, 0.1);
        assert_eq!(materials::TINTED_GLASS.metallic, 0.1);
    }
}
