//! C++-compatible float formatting.
//!
//! The C++ side uses `std::to_string(float)` in compliance messages
//! (e.g. `"Max span: " + std::to_string(maxSpan.value()) + " ft"`).
//! `std::to_string` for floating-point emits `sprintf("%f", x)` — six
//! decimal places. Rust's default `Display` gives the shortest
//! unambiguous representation, which would diverge.
//!
//! For byte-identical compliance messages we use [`cpp_float`] which
//! mirrors `std::to_string(float)`.

/// Mirrors `std::to_string(float)` — six decimal places, no exponent.
/// Examples (matches MSVC and glibc):
/// - `10.5` → `"10.500000"`
/// - `0.0`  → `"0.000000"`
/// - `-3.0` → `"-3.000000"`
#[must_use]
pub fn cpp_float(x: f32) -> String {
    format!("{x:.6}")
}

/// Mirrors `std::to_string(int)` — plain decimal, no leading zeros.
/// Same as Rust's default for integers but kept as a named helper so
/// the call sites read parallel to `cpp_float`.
#[must_use]
pub fn cpp_int(x: i32) -> String {
    x.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn six_decimal_places_for_whole_number() {
        assert_eq!(cpp_float(10.0), "10.000000");
    }

    #[test]
    fn six_decimal_places_for_half() {
        assert_eq!(cpp_float(10.5), "10.500000");
    }

    #[test]
    fn negative_zero_keeps_sign() {
        // C++ %f preserves the sign of zero — Rust does too.
        assert_eq!(cpp_float(-0.0), "-0.000000");
    }

    #[test]
    fn zero_is_six_zeros() {
        assert_eq!(cpp_float(0.0), "0.000000");
    }
}
