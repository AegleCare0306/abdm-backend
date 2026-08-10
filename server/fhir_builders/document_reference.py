"""
DocumentReference Resource Builder.

Used for every HI-type attachment except Prescription (bare Binary --
see binary.py) and DiagnosticReportRecord/Imaging (Media -- see media.py).
"""

from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceContent,
    DocumentReferenceContext,
)
from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime
from server.fhir_builders.attachment_utils import read_attachment


ABDM_DOCUMENT_REFERENCE_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentReference"


def build_document_reference(
    *,
    document_id,
    patient_id,
    encounter_id,
    title,
    creation_datetime,
    file_path=None,
    attachment_url=None,
):
    """
    Builds a DocumentReference wrapping either an inline base64 attachment
    (file_path given -- reads and base64-encodes the file at that
    repo-root-relative path) or a URL-referenced attachment (attachment_url
    given, e.g. "Binary/BIN-DOCREF0099" -- used by the "Binary +
    attachment.url" override path in health_information_data_service.py;
    no inline `data` is set in that case, matching the general HL7
    guidance that a URL-referenced Binary carries the actual bytes, not
    the DocumentReference). Exactly one of file_path/attachment_url must
    be given.

    Note: DocumentReference.context.encounter is a *list* field per the
    real FHIR R4 structure (fhir.resources.R4B enforces this) -- not a
    bare Reference as an earlier draft of this task's instructions
    described; flagged in the change report.
    """

    if bool(file_path) == bool(attachment_url):
        raise ValueError("build_document_reference requires exactly one of file_path or attachment_url")

    if file_path:
        content_type, data, _size_bytes = read_attachment(file_path)
        attachment_kwargs = {"contentType": content_type, "data": data}
    else:
        attachment_kwargs = {"url": attachment_url}

    attachment_kwargs["title"] = title
    if creation_datetime:
        attachment_kwargs["creation"] = to_fhir_datetime(creation_datetime)

    document_reference = DocumentReference(
        id=document_id,
        meta=Meta(profile=[ABDM_DOCUMENT_REFERENCE_PROFILE]),
        status="current",
        docStatus="final",
        subject=Reference(reference=f"Patient/{patient_id}"),
        context=DocumentReferenceContext(encounter=[Reference(reference=f"Encounter/{encounter_id}")]),
        content=[DocumentReferenceContent(attachment=Attachment(**attachment_kwargs))],
    )

    return document_reference.model_dump(mode="json", exclude_none=True)
