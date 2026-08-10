"""
Attachment instrumentation / comparison layer.

Captures, for each FHIR attachment resource (DocumentReference/Binary/
Media) built while assembling M2 bundles:
  1. payload size -- byte length of json.dumps(resource)
  2. encryption/transmission timing -- wall-clock spans around
     encrypt_health_data() and send_health_information_data()
  3. spec fit -- cross-referenced from attachment_spec.py (not measured
     here, just looked up for the report)

(4), error rate from storage/api_capture.jsonl, is NOT tracked here --
that's handled by tagging record_call()'s own log entries directly (see
server/callbacks/utils/api_capture.py's attachment_mechanisms parameter)
so failures can be correlated post-hoc by grepping/parsing that existing
log, per this task's instruction not to build a second log file for that
part.

STORAGE: in-memory only, for the lifetime of this process -- this is
deliberately a small instrumentation pass, not a persisted metrics
store. If this needs to survive process restarts or be queried
externally later, that's a follow-up, not implemented here.
"""

import json
import time
from contextlib import contextmanager

from server.fhir_builders.attachment_spec import spec_for


_payload_size_records = []
_timing_records = []

ATTACHMENT_RESOURCE_TYPES = ("DocumentReference", "Binary", "Media")


def record_payload_size(resource, *, hi_type, mechanism, sub_kind=None, care_context_reference=None):
    """
    Records the byte length of json.dumps(resource) for one built
    attachment resource, tagged with which HI type / mechanism produced
    it (and, for DiagnosticReport, which sub_kind -- "Lab" or "Imaging").
    """

    size_bytes = len(json.dumps(resource))

    _payload_size_records.append(
        {
            "resource_type": resource.get("resourceType"),
            "resource_id": resource.get("id"),
            "hi_type": hi_type,
            "sub_kind": sub_kind,
            "mechanism": mechanism,
            "care_context_reference": care_context_reference,
            "size_bytes": size_bytes,
        }
    )


@contextmanager
def time_block(label, **tags):
    """
    Wall-clock timer for one named span (e.g. "bundle_assembly",
    "encrypt", "transmit"), tagged with arbitrary key/value pairs (e.g.
    transaction_id, care_context_reference, mechanisms). Multiple spans
    sharing a tag (e.g. the same transaction_id) can be correlated back
    together by summarize() or by a caller reading _timing_records
    directly -- this captures "bundle assembly through encrypt to
    transmit" as three correlated sub-spans rather than one opaque timer
    spanning multiple functions/files, so where the time actually goes
    stays visible.
    """

    start = time.perf_counter()
    try:
        yield
    finally:
        duration_seconds = time.perf_counter() - start
        _timing_records.append(
            {
                "label": label,
                "tags": tags,
                "duration_seconds": duration_seconds,
            }
        )


def mechanisms_in_bundle(bundle):
    """
    Scans a built FHIR document Bundle dict for which attachment
    mechanism(s) it contains, by resourceType. Returns a sorted list of
    the ATTACHMENT_RESOURCE_TYPES found (possibly empty, possibly more
    than one -- e.g. an encounter with both a Prescription Binary and an
    Invoice DocumentReference).
    """

    found = set()
    for entry in bundle.get("entry", []):
        resource_type = entry.get("resource", {}).get("resourceType")
        if resource_type in ATTACHMENT_RESOURCE_TYPES:
            found.add(resource_type)
    return sorted(found)


def reset():
    """Clears all recorded metrics. Mainly for tests/manual reruns."""
    _payload_size_records.clear()
    _timing_records.clear()


def summarize():
    """
    Returns a structured comparison report: for each (hi_type, sub_kind,
    mechanism) combination seen, count/total/average payload size,
    cross-referenced against attachment_spec.py's spec-fit table (was
    this the spec-correct mechanism); and for each timing label, count/
    total/average duration.

    Deliberately just a dict -- no polished formatting. print(summarize())
    or json.dumps(summarize(), indent=2) is enough for this pass; flagged
    in the change report as something to revisit if this needs to become
    an actual report artifact later.
    """

    by_mechanism = {}
    for record in _payload_size_records:
        key = (record["hi_type"], record["sub_kind"], record["mechanism"])
        bucket = by_mechanism.setdefault(
            key,
            {"hi_type": record["hi_type"], "sub_kind": record["sub_kind"], "mechanism": record["mechanism"], "count": 0, "total_bytes": 0},
        )
        bucket["count"] += 1
        bucket["total_bytes"] += record["size_bytes"]

    payload_summary = []
    for (hi_type, sub_kind, mechanism), bucket in by_mechanism.items():
        spec = spec_for(hi_type, sub_kind)
        payload_summary.append(
            {
                **bucket,
                "average_bytes": bucket["total_bytes"] / bucket["count"] if bucket["count"] else 0,
                "spec_correct_mechanism": spec["mechanism"] if spec else None,
                "matches_spec": (spec is not None and spec["mechanism"] == mechanism),
            }
        )

    by_label = {}
    for record in _timing_records:
        bucket = by_label.setdefault(record["label"], {"label": record["label"], "count": 0, "total_seconds": 0.0})
        bucket["count"] += 1
        bucket["total_seconds"] += record["duration_seconds"]

    timing_summary = [
        {**bucket, "average_seconds": bucket["total_seconds"] / bucket["count"] if bucket["count"] else 0}
        for bucket in by_label.values()
    ]

    return {
        "payload_sizes": payload_summary,
        "timings": timing_summary,
    }
