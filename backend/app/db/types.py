from enum import StrEnum


class DevicePlatform(StrEnum):
    ANDROID = "ANDROID"
    IOS = "IOS"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    FAILED = "FAILED"
