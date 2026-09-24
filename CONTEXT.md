# Project Helios

Project Helios moves an aircraft between requested destinations within a surveyed operating volume and supervises its return to a dock.

## Language

**Tag**:
The ranging endpoint attached to the aircraft, whose location is measured relative to fixed anchors.

**Anchor**:
A fixed ranging endpoint with a surveyed antenna location.

**Collector anchor**:
The anchor that exposes the network's range reports to the localization host. It remains a ranging anchor; it is not the position solver.

**Range**:
A measured slant distance between tag and anchor antennas, not a horizontal distance or a coordinate.

**Position estimate**:
An estimate of the aircraft's current location, accompanied by timing and uncertainty.
_Avoid_: Waypoint, destination

**Waypoint**:
A requested three-dimensional aircraft location in a defined coordinate frame.
_Avoid_: Position estimate

**Dock**:
The fixed landing platform and reference location for the operating area.

**Relative altitude**:
Vertical displacement from an established altitude reference, distinct from clearance above the surface below the aircraft.
