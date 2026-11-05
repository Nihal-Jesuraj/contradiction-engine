"""Contradiction detectors.

Each detector takes evidence records and returns ``Conflict`` objects. A
detector never receives ground truth; scoring happens afterwards in
``models.score_conflicts``.

Detectors are added in later steps:

- ``device_state``: local activity while a device is off or asleep.
- ``location``: impossible travel between consecutive sightings.
- ``chronology``: messages timestamped before the messages they depend on.
- ``claims``: denied access that contradicts a login record.
"""
