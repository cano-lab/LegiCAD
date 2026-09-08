//! Per-element / per-space analysis results.
//!
//! Port of `types.hpp:414-435` (ThermalData, LightingData, AcousticData).

use serde::{Deserialize, Serialize};

/// Thermal analysis data for a structural element.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct ThermalData {
    /// Temperature in °F or °C (consumer decides).
    pub temperature: f32,
    /// U-value (thermal transmittance).
    pub u_value: f32,
    /// Heat loss in BTU/hr.
    pub heat_loss: f32,
    pub surface_temp: f32,
}

/// Lighting analysis data for a space.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct LightingData {
    /// Daylight factor as a percentage.
    pub daylight_factor: f32,
    pub illuminance_lux: f32,
    /// Lighting uniformity ratio.
    pub uniformity: f32,
    pub meets_code: bool,
}

/// Acoustic analysis data for a space.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct AcousticData {
    /// Reverberation time in seconds.
    pub rt60: f32,
    pub absorption_coeff: f32,
    /// Sound pressure level in dB.
    pub sound_level: f32,
    pub quality: String,
}
