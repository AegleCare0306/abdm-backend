"""Diagnosis Package"""

from dummy_emr.master_data.diagnoses.general_medicine import GENERAL_MEDICINE
from dummy_emr.master_data.diagnoses.cardiology import CARDIOLOGY
from dummy_emr.master_data.diagnoses.pulmonology import PULMONOLOGY
from dummy_emr.master_data.diagnoses.endocrinology import ENDOCRINOLOGY
from dummy_emr.master_data.diagnoses.orthopedics import ORTHOPEDICS
from dummy_emr.master_data.diagnoses.gynecology import GYNECOLOGY
from dummy_emr.master_data.diagnoses.pediatrics import PEDIATRICS
from dummy_emr.master_data.diagnoses.dermatology import DERMATOLOGY
from dummy_emr.master_data.diagnoses.ent import ENT
from dummy_emr.master_data.diagnoses.ophthalmology import OPHTHALMOLOGY
from dummy_emr.master_data.diagnoses.neurology import NEUROLOGY
from dummy_emr.master_data.diagnoses.urology import UROLOGY
from dummy_emr.master_data.diagnoses.psychiatry import PSYCHIATRY
from dummy_emr.master_data.diagnoses.surgery import SURGERY
from dummy_emr.master_data.diagnoses.emergency import EMERGENCY

DIAGNOSES = (
    GENERAL_MEDICINE
    + CARDIOLOGY
    + PULMONOLOGY
    + ENDOCRINOLOGY
    + ORTHOPEDICS
    + GYNECOLOGY
    + PEDIATRICS
    + DERMATOLOGY
    + ENT
    + OPHTHALMOLOGY
    + NEUROLOGY
    + UROLOGY
    + PSYCHIATRY
    + SURGERY
    + EMERGENCY
)
