//! Per-mode room catalog.
//!
//! A room type is just a string in the layout engine, but the catalog defines
//! which strings are legal for each [`BuildingMode`] and supplies their default
//! area/weight/zoning. This lets a Claude Code harness or manifest author know
//! exactly which rooms are available for a Part 9 house vs a Part 3 office vs
//! a mixed-use podium.

use crate::mode::BuildingMode;
use crate::Zone;

/// One entry in the room catalog.
#[derive(Debug, Clone, PartialEq)]
pub struct RoomCatalogEntry {
    /// Machine room type string (e.g. `"bedroom"`, `"office_open"`).
    pub room_type: String,
    /// Functional zone used for adjacency and layout.
    pub zone: Zone,
    /// Relative weight for area allocation (higher = absorbs more slack).
    pub default_weight: f32,
    /// Absolute minimum area in square feet.
    pub default_min_area: f32,
    /// Which modes this room type may appear in.
    pub allowed_modes: Vec<BuildingMode>,
    /// Optional major occupancy classification hint for Part 3.
    pub major_occupancy: Option<String>,
}

impl RoomCatalogEntry {
    fn new(
        room_type: &str,
        zone: Zone,
        weight: f32,
        min_area: f32,
        modes: &[BuildingMode],
    ) -> Self {
        Self {
            room_type: room_type.into(),
            zone,
            default_weight: weight,
            default_min_area: min_area,
            allowed_modes: modes.to_vec(),
            major_occupancy: None,
        }
    }

    fn with_occupancy(mut self, occ: &str) -> Self {
        self.major_occupancy = Some(occ.into());
        self
    }
}

/// Registry of room types available for a given mode.
#[derive(Debug, Clone)]
pub struct RoomCatalog {
    pub mode: BuildingMode,
    pub entries: Vec<RoomCatalogEntry>,
}

impl RoomCatalog {
    /// Build the catalog for a mode. The catalog is hardcoded here; future
    /// work may load overrides from a manifest or external file.
    #[must_use]
    pub fn for_mode(mode: BuildingMode) -> Self {
        let entries = match mode {
            BuildingMode::Part9 => part9_catalog(),
            BuildingMode::Part3 => part3_catalog(),
            BuildingMode::Mixed => mixed_catalog(),
        };
        Self { mode, entries }
    }

    /// Look up an entry by room type string.
    #[must_use]
    pub fn get(&self, room_type: &str) -> Option<&RoomCatalogEntry> {
        self.entries.iter().find(|e| e.room_type == room_type)
    }

    /// True if the room type is legal in this catalog.
    #[must_use]
    pub fn contains(&self, room_type: &str) -> bool {
        self.get(room_type).is_some()
    }

    /// All room type strings in the catalog.
    #[must_use]
    pub fn room_types(&self) -> Vec<String> {
        self.entries.iter().map(|e| e.room_type.clone()).collect()
    }

    /// Room types legal for the given mode (the catalog's own mode by default,
    /// but useful when filtering a mixed catalog).
    #[must_use]
    pub fn room_types_for(&self, mode: BuildingMode) -> Vec<String> {
        self.entries
            .iter()
            .filter(|e| e.allowed_modes.contains(&mode))
            .map(|e| e.room_type.clone())
            .collect()
    }

    /// Validate a list of room type strings against the catalog. Returns the
    /// first invalid type, or None if all are valid.
    #[must_use]
    pub fn validate_room_types(&self,
        types: &[&str],
    ) -> Option<String> {
        types
            .iter()
            .copied()
            .find(|t| !self.contains(t))
            .map(std::string::ToString::to_string)
    }
}

fn part9_catalog() -> Vec<RoomCatalogEntry> {
    vec![
        // Public
        RoomCatalogEntry::new("entry", Zone::Public, 2.0, 40.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("living", Zone::Public, 18.0, 160.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("great_room", Zone::Public, 20.0, 200.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("dining", Zone::Public, 8.0, 90.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("kitchen", Zone::Public, 10.0, 100.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("office", Zone::Public, 6.0, 90.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("foyer", Zone::Public, 4.0, 60.0, &[BuildingMode::Part9]),
        // Circulation
        RoomCatalogEntry::new("hallway", Zone::Circulation, 5.0, 40.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("corridor", Zone::Circulation, 4.0, 80.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("stairs", Zone::Circulation, 4.0, 70.0, &[BuildingMode::Part9]),
        // Service
        RoomCatalogEntry::new("mudroom", Zone::Service, 2.0, 40.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("pantry", Zone::Service, 1.0, 25.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("mechanical", Zone::Service, 2.0, 60.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("laundry", Zone::Service, 2.0, 35.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("garage", Zone::Service, 10.0, 220.0, &[BuildingMode::Part9]),
        // Private
        RoomCatalogEntry::new("primary_bedroom", Zone::Private, 12.0, 140.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("bedroom", Zone::Private, 9.0, 100.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("primary_bath", Zone::Private, 3.0, 50.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("bathroom", Zone::Private, 2.0, 40.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("powder_room", Zone::Private, 1.0, 20.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("walk_in_closet", Zone::Private, 2.0, 25.0, &[BuildingMode::Part9]),
        RoomCatalogEntry::new("closet", Zone::Private, 1.0, 15.0, &[BuildingMode::Part9]),
    ]
}

fn part3_catalog() -> Vec<RoomCatalogEntry> {
    vec![
        // Public / assembly / mercantile
        RoomCatalogEntry::new("retail", Zone::Public, 25.0, 800.0, &[BuildingMode::Part3])
            .with_occupancy("mercantile"),
        RoomCatalogEntry::new("restaurant", Zone::Public, 20.0, 600.0, &[BuildingMode::Part3])
            .with_occupancy("assembly"),
        RoomCatalogEntry::new("lobby", Zone::Public, 8.0, 200.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("reception", Zone::Public, 5.0, 100.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("foyer", Zone::Public, 4.0, 80.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("entry", Zone::Public, 2.0, 40.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("lounge", Zone::Public, 10.0, 150.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("study", Zone::Public, 6.0, 100.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        // Apartment / residential dwelling units
        RoomCatalogEntry::new("studio", Zone::Private, 8.0, 350.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("one_bedroom", Zone::Private, 10.0, 500.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("two_bedroom", Zone::Private, 12.0, 700.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("three_bedroom", Zone::Private, 14.0, 900.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("suite", Zone::Private, 9.0, 400.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        // Residential common / amenity spaces
        RoomCatalogEntry::new("common_room", Zone::Public, 7.0, 300.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("dining_hall", Zone::Public, 8.0, 400.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("fitness_room", Zone::Public, 5.0, 250.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("mail_room", Zone::Service, 2.0, 80.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        // Business / office
        RoomCatalogEntry::new("office_open", Zone::Public, 18.0, 600.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("office_private", Zone::Public, 6.0, 120.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("conference", Zone::Public, 8.0, 150.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        RoomCatalogEntry::new("classroom", Zone::Public, 12.0, 600.0, &[BuildingMode::Part3])
            .with_occupancy("assembly"),
        RoomCatalogEntry::new("auditorium", Zone::Public, 20.0, 1000.0, &[BuildingMode::Part3])
            .with_occupancy("assembly"),
        RoomCatalogEntry::new("kitchenette", Zone::Service, 2.0, 40.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        // Circulation
        RoomCatalogEntry::new("corridor", Zone::Circulation, 6.0, 120.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("hallway", Zone::Circulation, 4.0, 80.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("stairs", Zone::Circulation, 5.0, 120.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("elevator", Zone::Circulation, 2.0, 25.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("shaft", Zone::Circulation, 1.0, 16.0, &[BuildingMode::Part3]),
        // Service
        RoomCatalogEntry::new("washroom", Zone::Service, 4.0, 80.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("mechanical", Zone::Service, 3.0, 100.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("electrical", Zone::Service, 1.5, 40.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("storage", Zone::Service, 4.0, 100.0, &[BuildingMode::Part3]),
        RoomCatalogEntry::new("loading_dock", Zone::Service, 10.0, 400.0, &[BuildingMode::Part3])
            .with_occupancy("industrial"),
        RoomCatalogEntry::new("parking", Zone::Service, 15.0, 800.0, &[BuildingMode::Part3])
            .with_occupancy("parking"),
        RoomCatalogEntry::new("janitor", Zone::Service, 1.0, 20.0, &[BuildingMode::Part3]),
        // Residential service / support
        RoomCatalogEntry::new("storage_locker", Zone::Service, 1.0, 25.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("laundry_room", Zone::Service, 3.0, 100.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("management_office", Zone::Service, 4.0, 120.0, &[BuildingMode::Part3])
            .with_occupancy("business"),
        // Dorm / college-residence rooms
        RoomCatalogEntry::new("dorm_single", Zone::Private, 6.0, 120.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("dorm_double", Zone::Private, 8.0, 180.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("shared_washroom", Zone::Service, 4.0, 120.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
        RoomCatalogEntry::new("study_lounge", Zone::Public, 6.0, 250.0, &[BuildingMode::Part3])
            .with_occupancy("residential"),
    ]
}

fn mixed_catalog() -> Vec<RoomCatalogEntry> {
    // Mixed mode allows any room from either Part 9 or Part 3. We reuse the
    // entries from both catalogs and widen their allowed_modes.
    let mut entries = part9_catalog();
    for e in &mut entries {
        if !e.allowed_modes.contains(&BuildingMode::Mixed) {
            e.allowed_modes.push(BuildingMode::Mixed);
        }
    }
    let mut p3 = part3_catalog();
    for e in &mut p3 {
        if !e.allowed_modes.contains(&BuildingMode::Mixed) {
            e.allowed_modes.push(BuildingMode::Mixed);
        }
    }
    entries.extend(p3);
    entries
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn part9_has_residential_rooms() {
        let cat = RoomCatalog::for_mode(BuildingMode::Part9);
        assert!(cat.contains("bedroom"));
        assert!(cat.contains("kitchen"));
        assert!(!cat.contains("retail"));
        assert!(!cat.contains("elevator"));
    }

    #[test]
    fn part3_has_commercial_rooms() {
        let cat = RoomCatalog::for_mode(BuildingMode::Part3);
        assert!(cat.contains("retail"));
        assert!(cat.contains("office_open"));
        assert!(cat.contains("elevator"));
        assert!(cat.contains("corridor"));
        assert!(!cat.contains("bedroom"));
    }

    #[test]
    fn part3_has_apartment_types() {
        let cat = RoomCatalog::for_mode(BuildingMode::Part3);
        assert!(cat.contains("studio"));
        assert!(cat.contains("one_bedroom"));
        assert!(cat.contains("two_bedroom"));
        assert!(cat.contains("suite"));
        assert!(cat.contains("common_room"));
        assert!(cat.contains("dining_hall"));
        assert!(cat.contains("storage_locker"));
        assert!(cat.contains("laundry_room"));
    }

    #[test]
    fn mixed_has_both() {
        let cat = RoomCatalog::for_mode(BuildingMode::Mixed);
        assert!(cat.contains("bedroom"));
        assert!(cat.contains("retail"));
        assert!(cat.contains("elevator"));
        assert!(cat.contains("studio"));
        assert!(cat.contains("common_room"));
    }

    #[test]
    fn part3_has_dorm_rooms() {
        let cat = RoomCatalog::for_mode(BuildingMode::Part3);
        assert!(cat.contains("dorm_single"));
        assert!(cat.contains("dorm_double"));
        assert!(cat.contains("shared_washroom"));
        assert!(cat.contains("study_lounge"));
    }

    #[test]
    fn validate_room_types_reports_unknown() {
        let cat = RoomCatalog::for_mode(BuildingMode::Part9);
        assert_eq!(
            cat.validate_room_types(&["bedroom", "kitchen", "retail"]),
            Some("retail".into())
        );
        assert!(cat.validate_room_types(&["bedroom", "kitchen"]).is_none());
    }

    #[test]
    fn room_types_for_filters_by_mode() {
        let mixed = RoomCatalog::for_mode(BuildingMode::Mixed);
        assert!(mixed.room_types_for(BuildingMode::Part9).contains(&"bedroom".to_string()));
        assert!(mixed.room_types_for(BuildingMode::Part3).contains(&"retail".to_string()));
        assert!(!mixed.room_types_for(BuildingMode::Part9).contains(&"retail".to_string()));
    }
}
