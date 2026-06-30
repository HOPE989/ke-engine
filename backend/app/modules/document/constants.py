from enum import StrEnum


class DocumentStatus(StrEnum):
    INIT = "INIT"
    UPLOADED = "UPLOADED"
    CONVERTING = "CONVERTING"
    CONVERTED = "CONVERTED"
