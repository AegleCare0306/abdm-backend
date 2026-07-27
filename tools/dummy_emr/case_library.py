"""
Clinical Case Library.
"""

CLINICAL_CASES = [

    {

        "case_id":"CASE001",

        "name":"Essential Hypertension",

        "encounter":{

            "type":"OPD",

            "department":"General Medicine",

            "chief_complaint":"Headache",

            "visit_reason":"Follow-up"

        },

        "condition":{

            "name":"Essential Hypertension",

            "icd10":"I10"

        },

        "medications":[

            "MED000002",

            "MED000003"

        ],

        "observations":[

            "OBS000001",

            "OBS000002"

        ],

        "diagnostic_reports":[

            "LAB000003"

        ],

        "procedures":[

        ],

        "documents":[

            "Prescription"

        ],

        "immunizations":[

        ]

    },

    {

        "case_id":"CASE002",

        "name":"Type 2 Diabetes",

        "encounter":{

            "type":"OPD",

            "department":"General Medicine",

            "chief_complaint":"High Blood Sugar",

            "visit_reason":"Follow-up"

        },

        "condition":{

            "name":"Type 2 Diabetes Mellitus",

            "icd10":"E11"

        },

        "medications":[

            "MED000004"

        ],

        "observations":[

            "OBS000003",

            "OBS000002"

        ],

        "diagnostic_reports":[

            "LAB000002"

        ],

        "procedures":[

        ],

        "documents":[

            "Prescription"

        ],

        "immunizations":[

        ]

    }

]