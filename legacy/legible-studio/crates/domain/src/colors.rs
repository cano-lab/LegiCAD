//! Stress / thermal / lighting / acoustic color palettes.
//!
//! Port of `types.hpp:438-501` (the four `XxxColors` namespaces). The
//! interpolation formulas are reproduced verbatim from the C++ — the goal
//! is bit-equivalent gradient output so that visualizations match.

use glam::Vec3;

/// Stress visualization gradient — green (safe) → yellow → orange → red (failure).
pub struct StressColors;

impl StressColors {
    pub const SAFE: Vec3 = Vec3::new(0.133, 0.773, 0.369); // #22c55e
    pub const WARNING: Vec3 = Vec3::new(0.918, 0.702, 0.031); // #eab308
    pub const CRITICAL: Vec3 = Vec3::new(0.976, 0.451, 0.086); // #f97316
    pub const FAILURE: Vec3 = Vec3::new(0.937, 0.267, 0.267); // #ef4444

    /// Stress → color. Same breakpoints as the C++.
    #[must_use]
    pub fn from_stress(stress: f32) -> Vec3 {
        if stress < 0.7 {
            return Self::SAFE;
        }
        if stress < 0.9 {
            return Self::SAFE.lerp(Self::WARNING, (stress - 0.7) / 0.2);
        }
        if stress < 1.0 {
            return Self::WARNING.lerp(Self::CRITICAL, (stress - 0.9) / 0.1);
        }
        Self::CRITICAL.lerp(Self::FAILURE, ((stress - 1.0) / 0.5).min(1.0))
    }
}

/// Thermal color gradient — cold blue → cyan → green → gold → hot red-orange.
pub struct ThermalColors;

impl ThermalColors {
    pub const COLD: Vec3 = Vec3::new(0.118, 0.565, 1.000); // #1E90FF
    pub const COOL: Vec3 = Vec3::new(0.000, 0.808, 0.820); // #00CED1
    pub const NEUTRAL: Vec3 = Vec3::new(0.565, 0.933, 0.565); // #90EE90
    pub const WARM: Vec3 = Vec3::new(1.000, 0.843, 0.000); // #FFD700
    pub const HOT: Vec3 = Vec3::new(1.000, 0.271, 0.000); // #FF4500

    #[must_use]
    pub fn from_temperature(temp: f32, min_temp: f32, max_temp: f32) -> Vec3 {
        let t = ((temp - min_temp) / (max_temp - min_temp)).clamp(0.0, 1.0);
        if t < 0.25 {
            return Self::COLD.lerp(Self::COOL, t * 4.0);
        }
        if t < 0.50 {
            return Self::COOL.lerp(Self::NEUTRAL, (t - 0.25) * 4.0);
        }
        if t < 0.75 {
            return Self::NEUTRAL.lerp(Self::WARM, (t - 0.50) * 4.0);
        }
        Self::WARM.lerp(Self::HOT, (t - 0.75) * 4.0)
    }

    /// Convenience: C++ defaults are min=50°F, max=90°F.
    #[must_use]
    pub fn from_temperature_default(temp: f32) -> Vec3 {
        Self::from_temperature(temp, 50.0, 90.0)
    }
}

/// Lighting color gradient — dark blue-gray → bright yellow → glare.
pub struct LightingColors;

impl LightingColors {
    pub const DARK: Vec3 = Vec3::new(0.157, 0.157, 0.235);
    pub const DIM: Vec3 = Vec3::new(0.392, 0.392, 0.471);
    pub const ADEQUATE: Vec3 = Vec3::new(0.784, 0.784, 0.627);
    pub const BRIGHT: Vec3 = Vec3::new(1.000, 0.980, 0.804);
    pub const GLARE: Vec3 = Vec3::new(1.000, 1.000, 0.878);

    #[must_use]
    pub fn from_lux(lux: f32, target_lux: f32) -> Vec3 {
        let ratio = lux / target_lux;
        if ratio < 0.3 {
            return Self::DARK.lerp(Self::DIM, ratio / 0.3);
        }
        if ratio < 0.7 {
            return Self::DIM.lerp(Self::ADEQUATE, (ratio - 0.3) / 0.4);
        }
        if ratio < 1.0 {
            return Self::ADEQUATE.lerp(Self::BRIGHT, (ratio - 0.7) / 0.3);
        }
        Self::BRIGHT.lerp(Self::GLARE, (ratio - 1.0).min(1.0))
    }

    /// Convenience: C++ default target is 500 lux.
    #[must_use]
    pub fn from_lux_default(lux: f32) -> Vec3 {
        Self::from_lux(lux, 500.0)
    }
}

/// Acoustic color gradient — dead (slate blue) → optimal (green) → reverberant (crimson).
pub struct AcousticColors;

impl AcousticColors {
    pub const DEAD: Vec3 = Vec3::new(0.282, 0.239, 0.545);
    pub const DRY: Vec3 = Vec3::new(0.416, 0.353, 0.804);
    pub const OPTIMAL: Vec3 = Vec3::new(0.486, 0.988, 0.000);
    pub const LIVE: Vec3 = Vec3::new(1.000, 0.647, 0.000);
    pub const REVERB: Vec3 = Vec3::new(0.863, 0.078, 0.235);

    #[must_use]
    pub fn from_rt60(rt60: f32, target_rt60: f32) -> Vec3 {
        let ratio = rt60 / target_rt60;
        if ratio < 0.5 {
            return Self::DEAD.lerp(Self::DRY, ratio * 2.0);
        }
        if ratio < 1.0 {
            return Self::DRY.lerp(Self::OPTIMAL, (ratio - 0.5) * 2.0);
        }
        if ratio < 1.5 {
            return Self::OPTIMAL.lerp(Self::LIVE, (ratio - 1.0) * 2.0);
        }
        Self::LIVE.lerp(Self::REVERB, (ratio - 1.5).min(1.0))
    }

    /// Convenience: C++ default target is 0.6s.
    #[must_use]
    pub fn from_rt60_default(rt60: f32) -> Vec3 {
        Self::from_rt60(rt60, 0.6)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stress_below_threshold_is_safe() {
        // Anything below 0.7 is solid SAFE.
        assert_eq!(StressColors::from_stress(0.0), StressColors::SAFE);
        assert_eq!(StressColors::from_stress(0.5), StressColors::SAFE);
        assert_eq!(StressColors::from_stress(0.69), StressColors::SAFE);
    }

    #[test]
    fn stress_at_break_lerps() {
        // stress=0.8 is halfway between SAFE and WARNING.
        let c = StressColors::from_stress(0.8);
        let expected = StressColors::SAFE.lerp(StressColors::WARNING, 0.5);
        assert!((c - expected).length() < 1e-6);
    }

    #[test]
    fn stress_well_over_1_caps_at_failure() {
        let c = StressColors::from_stress(2.0);
        assert_eq!(c, StressColors::FAILURE);
    }

    #[test]
    fn thermal_clamps_below_min() {
        assert_eq!(
            ThermalColors::from_temperature(-100.0, 50.0, 90.0),
            ThermalColors::COLD
        );
    }

    #[test]
    fn thermal_clamps_above_max() {
        assert_eq!(
            ThermalColors::from_temperature(1000.0, 50.0, 90.0),
            ThermalColors::HOT
        );
    }

    #[test]
    fn acoustic_optimal_at_target() {
        // At ratio = 1.0 exactly, we sit at OPTIMAL (boundary case).
        let c = AcousticColors::from_rt60(0.6, 0.6);
        assert_eq!(c, AcousticColors::OPTIMAL);
    }
}
