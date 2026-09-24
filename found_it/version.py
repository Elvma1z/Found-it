"""The app's version and its release notes.

The What's New splash is driven entirely from CHANGELOG, so shipping an
update means adding one entry here and bumping APP_VERSION - no GUI code
needs to change. Keep APP_VERSION in sync with MyAppVersion in
FoundItSetup.iss so the installer and the splash agree.
"""

APP_VERSION = "1.1.0"

# What a settings file that predates last_seen_version is assumed to have
# seen. Those installs are upgrades, not first runs, so they get the release
# notes for everything after this - not the first-time tutorial.
PRE_VERSIONING_VERSION = "1.0.0"

# Newest first. "added" is new capability, "changed" is behaviour that moved
# or now works differently - the two are shown as separate lists so a user
# skimming the splash can tell "there's a new thing" from "the thing you
# knew moved".
CHANGELOG = [
    {
        "version": "1.1.0",
        "date": "August 2026",
        "added": [
            "A 3D view of your room: in Room Setup, press \"3D View\" to stand every "
            "piece of furniture up at its real height instead of reading a flat floor plan.",
            "A dedicated Cameras tab in the top bar - add, discover, name, and "
            "enable/disable cameras from one screen, each with its own settings page.",
            "Live tracking for a selected item: pick something in Found Items and its "
            "position stays highlighted as you switch between camera views.",
            "A first-run tutorial and this What's New splash. Both can be reopened any "
            "time from Settings \u2192 Help.",
        ],
        "changed": [
            "Room Setup now uses imperial units - room width and depth in feet, "
            "furniture height in inches.",
            "Camera management moved out of Room Setup and into the new Cameras tab.",
            "Room Setup's side panels (Zones / Furniture, Drawers, Detected Objects) are "
            "separate docks again, and each one collapses to its title bar.",
            "Buttons throughout the app now carry icons, and destructive actions "
            "(delete, remove, cancel) are styled red so they read as destructive.",
        ],
    },
    {
        "version": "1.0.0",
        "date": "August 2026",
        "added": [
            "First release: multi-room item tracking from live cameras, a room layout "
            "editor with zones and drawer-level spots, whole-PC photo and file search "
            "with face recognition and reverse image search, phone search over USB, "
            "nine themes, and a customizable panel layout.",
        ],
        "changed": [],
    },
]


def parse_version(text: str) -> tuple:
    """"1.10.2" -> (1, 10, 2). Anything unparseable sorts before every real
    release, so a corrupted saved version shows the notes rather than
    silently swallowing them."""
    parts = []
    for chunk in str(text or "").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def releases_since(last_seen: str) -> list:
    """Every changelog entry newer than `last_seen`, newest first.

    Skipping updates is normal (someone installs 1.0.0, then jumps to 1.3.0),
    so this returns all of the missed releases rather than only the latest -
    otherwise the notes for the versions they skipped would never be seen.
    """
    if not last_seen:
        return []
    floor = parse_version(last_seen)
    return [rel for rel in CHANGELOG if parse_version(rel["version"]) > floor]


def current_release() -> dict:
    for rel in CHANGELOG:
        if rel["version"] == APP_VERSION:
            return rel
    return CHANGELOG[0] if CHANGELOG else {"version": APP_VERSION, "date": "", "added": [], "changed": []}
