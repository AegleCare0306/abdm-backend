"""
Media Resource Builder.

Used for DiagnosticReportRecord's Imaging sub-profile attachment (X-rays,
etc.) -- the real ABDM IG's DiagnosticReportImaging profile (a profile on
the DiagnosticReport resource itself, parallel to the existing
DiagnosticReportLab) requires media as a mandatory 1..* backbone element
on that DiagnosticReport resource (media.link -> Reference(Media)), not a
bare Media resource referenced only from the Composition section.

Implementing that properly is a 4th resource-builder area (a
DiagnosticReportImaging variant of diagnostic_report.py, with its own
mandatory resultsInterpreter/conclusion/code fields) beyond this task's
Part A scope (document_reference.py, binary.py, media.py). Flagged in the
change report as a "stop, don't guess, report options" item per this
task's instructions -- this builder produces a standalone Media resource,
referenced directly from the Composition's Investigations section
alongside/instead of the Lab DiagnosticReport, which is sufficient to
exercise the Media mechanism and Part D's payload-size/timing comparison,
but is not the fully spec-correct DiagnosticReportImaging wrapper.

fhir.resources.R4B.media.Media requires `status` (enforced by a runtime
validator even though it's not in the model's declared "required" list)
in addition to `content` -- confirmed by testing against the installed
library rather than assumed.
"""

from fhir.resources.R4B.media import Media
from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime
from server.fhir_builders.attachment_utils import read_attachment


ABDM_MEDIA_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Media"


def build_media(
    *,
    media_id,
    patient_id,
    encounter_id,
    title,
    creation_datetime,
    file_path,
):

    content_type, data, _size_bytes = read_attachment(file_path)

    attachment_kwargs = {"contentType": content_type, "data": data}
    if title:
        attachment_kwargs["title"] = title
    if creation_datetime:
        attachment_kwargs["creation"] = to_fhir_datetime(creation_datetime)

    media = Media(
        id=media_id,
        meta=Meta(profile=[ABDM_MEDIA_PROFILE]),
        status="completed",
        subject=Reference(reference=f"Patient/{patient_id}"),
        encounter=Reference(reference=f"Encounter/{encounter_id}"),
        content=Attachment(**attachment_kwargs),
    )

    return media.model_dump(mode="json", exclude_none=True)
