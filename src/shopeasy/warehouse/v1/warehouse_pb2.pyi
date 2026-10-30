from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Condition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONDITION_UNSPECIFIED: _ClassVar[Condition]
    NEUWERTIG: _ClassVar[Condition]
    GETRAGEN: _ClassVar[Condition]
    BESCHAEDIGT: _ClassVar[Condition]
    UNVOLLSTAENDIG: _ClassVar[Condition]
    FALSCHER_ARTIKEL: _ClassVar[Condition]
CONDITION_UNSPECIFIED: Condition
NEUWERTIG: Condition
GETRAGEN: Condition
BESCHAEDIGT: Condition
UNVOLLSTAENDIG: Condition
FALSCHER_ARTIKEL: Condition

class GoodsReceiptRequest(_message.Message):
    __slots__ = ("retouren_id", "scanner_id", "scanned_at")
    RETOUREN_ID_FIELD_NUMBER: _ClassVar[int]
    SCANNER_ID_FIELD_NUMBER: _ClassVar[int]
    SCANNED_AT_FIELD_NUMBER: _ClassVar[int]
    retouren_id: str
    scanner_id: str
    scanned_at: str
    def __init__(self, retouren_id: _Optional[str] = ..., scanner_id: _Optional[str] = ..., scanned_at: _Optional[str] = ...) -> None: ...

class GoodsReceiptResponse(_message.Message):
    __slots__ = ("retouren_id", "already_cancelled", "pruef_frist")
    RETOUREN_ID_FIELD_NUMBER: _ClassVar[int]
    ALREADY_CANCELLED_FIELD_NUMBER: _ClassVar[int]
    PRUEF_FRIST_FIELD_NUMBER: _ClassVar[int]
    retouren_id: str
    already_cancelled: bool
    pruef_frist: str
    def __init__(self, retouren_id: _Optional[str] = ..., already_cancelled: _Optional[bool] = ..., pruef_frist: _Optional[str] = ...) -> None: ...

class InspectionRequest(_message.Message):
    __slots__ = ("retouren_id", "condition", "inspector", "note", "photo_refs")
    RETOUREN_ID_FIELD_NUMBER: _ClassVar[int]
    CONDITION_FIELD_NUMBER: _ClassVar[int]
    INSPECTOR_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    PHOTO_REFS_FIELD_NUMBER: _ClassVar[int]
    retouren_id: str
    condition: Condition
    inspector: str
    note: str
    photo_refs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, retouren_id: _Optional[str] = ..., condition: _Optional[_Union[Condition, str]] = ..., inspector: _Optional[str] = ..., note: _Optional[str] = ..., photo_refs: _Optional[_Iterable[str]] = ...) -> None: ...

class InspectionResponse(_message.Message):
    __slots__ = ("retouren_id", "condition", "recorded_at")
    RETOUREN_ID_FIELD_NUMBER: _ClassVar[int]
    CONDITION_FIELD_NUMBER: _ClassVar[int]
    RECORDED_AT_FIELD_NUMBER: _ClassVar[int]
    retouren_id: str
    condition: Condition
    recorded_at: str
    def __init__(self, retouren_id: _Optional[str] = ..., condition: _Optional[_Union[Condition, str]] = ..., recorded_at: _Optional[str] = ...) -> None: ...

class RetourenIdRequest(_message.Message):
    __slots__ = ("retouren_id",)
    RETOUREN_ID_FIELD_NUMBER: _ClassVar[int]
    retouren_id: str
    def __init__(self, retouren_id: _Optional[str] = ...) -> None: ...
