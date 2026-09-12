"""
Thin wrapper kept for call-site stability (discover_service.py,
generate_token_service.py, link_confirm_service.py all import
search_patient from here) -- the real implementation now lives in
dummy_emr_repository.py, which queries Postgres's patient_records table
instead of reading server/data/patient_records.csv.
"""

from server.callbacks.repository.dummy_emr_repository import search_patient

__all__ = ["search_patient"]
