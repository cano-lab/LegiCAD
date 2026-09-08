//! OBC life-safety alarm rules: smoke alarms (9.10.19) and CO alarms (9.33.4).
//!
//! Pure rule predicates — *where* an alarm goes in a room is a placement
//! decision left to the consumer (the solver); this module answers "what is
//! required". First category of the deterministic rules-engine annotation
//! pass.

/// A smoke alarm is required in **each bedroom** (OBC 9.10.19.3).
pub const SMOKE_IN_EACH_BEDROOM: bool = true;

/// A smoke alarm is required on **each storey** — on a storey with bedrooms it
/// serves the sleeping area (in the hallway/space between the bedrooms and the
/// rest of the storey); a storey without bedrooms still needs one
/// (OBC 9.10.19.3). Smoke alarms in a dwelling unit must be interconnected.
#[must_use]
pub const fn smoke_on_each_storey() -> bool {
    true
}

/// A CO alarm is required adjacent to each sleeping area when the dwelling has
/// a fuel-fired appliance or an attached / built-in storage garage
/// (OBC 9.33.4). Returns whether a CO alarm is required given those conditions.
#[must_use]
pub fn requires_co_alarm(attached_garage: bool, fuel_fired_appliance: bool) -> bool {
    attached_garage || fuel_fired_appliance
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[allow(clippy::assertions_on_constants)]
    fn smoke_alarms_always_required() {
        assert!(SMOKE_IN_EACH_BEDROOM);
        assert!(smoke_on_each_storey());
    }

    #[test]
    fn co_required_with_attached_garage_or_fuel_appliance() {
        assert!(requires_co_alarm(true, false)); // attached garage
        assert!(requires_co_alarm(false, true)); // fuel-fired appliance
        assert!(requires_co_alarm(true, true));
        assert!(!requires_co_alarm(false, false)); // all-electric, no garage
    }
}
