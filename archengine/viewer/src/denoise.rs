//! Image denoising for the path tracer's HDR output.
//!
//! The C++ never integrated Intel Open Image Denoise — `applyDenoising`
//! only ships the 3×3 edge-aware CPU filter with a "for production quality,
//! integrate OIDN" comment (path_tracer.cpp:796). This module delivers that
//! integration behind the `denoise-oidn` cargo feature:
//!
//! - **With the feature** (and the OIDN library installed —
//!   `brew install open-image-denoise` on the M1 target, discoverable via
//!   pkg-config), the progressive HDR result is denoised with OIDN's `RT`
//!   ray-tracing filter.
//! - **Without the feature**, [`denoise_oidn`] reports
//!   [`DenoiseError::Unavailable`] and the caller falls back to the verbatim
//!   3×3 CPU filter — so default builds never require the native library.
//!
//! OIDN works on packed float3 RGB; the tracer's accumulation buffer is
//! RGBA-f32, so alpha is stripped before filtering and restored after.

/// Why denoising could not run (the caller then falls back to the CPU
/// filter — this is a quality tradeoff, never a hard failure).
#[derive(Debug, thiserror::Error)]
pub enum DenoiseError {
    /// Built without the `denoise-oidn` feature (or the native library is
    /// not installed): OIDN is not available in this binary.
    #[error("OIDN not compiled in (enable the `denoise-oidn` feature)")]
    Unavailable,
    /// OIDN itself reported a failure (device creation, filter setup or
    /// execution).
    #[cfg(feature = "denoise-oidn")]
    #[error("OIDN: {0}")]
    Oidn(#[from] oidn::Error),
}

/// Denoise an RGBA-f32 HDR image in place with OIDN's `RT` filter.
///
/// `pixels` must be `width * height * 4` floats; alpha is preserved.
/// HDR mode is enabled and no sRGB curve is assumed (the tracer outputs
/// linear HDR — tonemapping happens afterwards, as in the C++).
#[cfg(feature = "denoise-oidn")]
pub fn denoise_oidn(
    pixels: &mut [f32],
    width: u32,
    height: u32,
) -> Result<(), DenoiseError> {
    let count = (width as usize) * (height as usize);
    assert_eq!(pixels.len(), count * 4, "RGBA-f32 pixel buffer size");

    // Strip alpha — OIDN filters packed float3 RGB.
    let mut rgb = Vec::with_capacity(count * 3);
    for px in pixels.chunks_exact(4) {
        rgb.extend_from_slice(&px[..3]);
    }

    let device = oidn::Device::new()?;
    let mut output = vec![0.0f32; rgb.len()];
    oidn::RayTracing::try_new(&device)?
        .hdr(true)
        .srgb(false)
        .image_dimensions(width as usize, height as usize)
        .filter(&rgb, &mut output)?;

    for (px, out) in pixels.chunks_exact_mut(4).zip(output.chunks_exact(3)) {
        px[..3].copy_from_slice(out);
    }
    Ok(())
}

/// Without the `denoise-oidn` feature this always reports
/// [`DenoiseError::Unavailable`]; the caller falls back to the CPU filter.
#[cfg(not(feature = "denoise-oidn"))]
pub fn denoise_oidn(
    _pixels: &mut [f32],
    _width: u32,
    _height: u32,
) -> Result<(), DenoiseError> {
    Err(DenoiseError::Unavailable)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Without the feature the stub must report Unavailable (with the
    /// feature this test still passes on machines lacking the native
    /// library only if OIDN errors — either way no panic, no UB).
    #[test]
    #[cfg(not(feature = "denoise-oidn"))]
    fn stub_reports_unavailable() {
        let mut px = vec![0.5f32; 4 * 4 * 4];
        let err = denoise_oidn(&mut px, 4, 4).unwrap_err();
        assert!(matches!(err, DenoiseError::Unavailable));
    }

    /// Buffer-size contract is enforced (feature-enabled builds only).
    #[test]
    #[cfg(feature = "denoise-oidn")]
    #[should_panic(expected = "RGBA-f32 pixel buffer size")]
    fn rejects_wrong_buffer_size() {
        let mut px = vec![0.0f32; 10];
        let _ = denoise_oidn(&mut px, 4, 4);
    }
}
