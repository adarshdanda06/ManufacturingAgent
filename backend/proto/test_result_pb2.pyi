from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TestSpec(_message.Message):
    __slots__ = ("name", "subsystem", "description", "cost_s")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SUBSYSTEM_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    COST_S_FIELD_NUMBER: _ClassVar[int]
    name: str
    subsystem: str
    description: str
    cost_s: float
    def __init__(self, name: _Optional[str] = ..., subsystem: _Optional[str] = ..., description: _Optional[str] = ..., cost_s: _Optional[float] = ...) -> None: ...

class TestCatalog(_message.Message):
    __slots__ = ("unit_id", "tests")
    UNIT_ID_FIELD_NUMBER: _ClassVar[int]
    TESTS_FIELD_NUMBER: _ClassVar[int]
    unit_id: str
    tests: _containers.RepeatedCompositeFieldContainer[TestSpec]
    def __init__(self, unit_id: _Optional[str] = ..., tests: _Optional[_Iterable[_Union[TestSpec, _Mapping]]] = ...) -> None: ...

class TestResult(_message.Message):
    __slots__ = ("unit_id", "test_name", "passed", "cost_s", "readings", "failures", "run_index", "unit_total_test_time_s")
    UNIT_ID_FIELD_NUMBER: _ClassVar[int]
    TEST_NAME_FIELD_NUMBER: _ClassVar[int]
    PASSED_FIELD_NUMBER: _ClassVar[int]
    COST_S_FIELD_NUMBER: _ClassVar[int]
    READINGS_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    RUN_INDEX_FIELD_NUMBER: _ClassVar[int]
    UNIT_TOTAL_TEST_TIME_S_FIELD_NUMBER: _ClassVar[int]
    unit_id: str
    test_name: str
    passed: bool
    cost_s: float
    readings: _struct_pb2.Struct
    failures: _containers.RepeatedScalarFieldContainer[str]
    run_index: int
    unit_total_test_time_s: float
    def __init__(self, unit_id: _Optional[str] = ..., test_name: _Optional[str] = ..., passed: _Optional[bool] = ..., cost_s: _Optional[float] = ..., readings: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., failures: _Optional[_Iterable[str]] = ..., run_index: _Optional[int] = ..., unit_total_test_time_s: _Optional[float] = ...) -> None: ...

class ReworkResult(_message.Message):
    __slots__ = ("unit_id", "action", "target", "suite_passed", "failing_tests", "cost_s")
    UNIT_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    SUITE_PASSED_FIELD_NUMBER: _ClassVar[int]
    FAILING_TESTS_FIELD_NUMBER: _ClassVar[int]
    COST_S_FIELD_NUMBER: _ClassVar[int]
    unit_id: str
    action: str
    target: str
    suite_passed: bool
    failing_tests: _containers.RepeatedScalarFieldContainer[str]
    cost_s: float
    def __init__(self, unit_id: _Optional[str] = ..., action: _Optional[str] = ..., target: _Optional[str] = ..., suite_passed: _Optional[bool] = ..., failing_tests: _Optional[_Iterable[str]] = ..., cost_s: _Optional[float] = ...) -> None: ...
