"""
Binary Resource Builder.

Used for PrescriptionRecord's attachment slot -- the only ABDM HI type
whose profile attaches via a bare Binary resource (direct entry) rather
than a DocumentReference. Also used, paired with a DocumentReference-via-
attachment.url, when ATTACHMENT_STRATEGY_OVERRIDE forces a normally
DocumentReference/Media-attaching HI type onto the general HL7
large-file (attachment.url -> separate Binary) pattern -- see
health_information_data_service.py.

Per FHIR R4 spec, Binary has no subject/context/id-linking fields beyond
contentType + data -- confirmed against fhir.resources.R4B.binary.Binary,
so none are added here.
"""

from fhir.resources.R4B.binary import Binary

from server.fhir_builders.attachment_utils import read_attachment


def build_binary(*, binary_id, file_path):

    content_type, data, _size_bytes = read_attachment(file_path)

    binary = Binary(
        id=binary_id,
        contentType=content_type,
        data=data,
    )

    return binary.model_dump(mode="json", exclude_none=True)
