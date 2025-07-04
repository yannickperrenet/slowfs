import resource
import typing

class ValueRange(typing.NamedTuple):
    min: int
    max: int

type Byte = typing.Annotated[int, ValueRange(0, 255)]

class Lt(typing.NamedTuple):
    """Lt(x) implies that the value must be less than x."""
    le: int

type Err = typing.Annotated[int, Lt(0)]
type Success = typing.Literal[0]
type ResultInt = Err | Success

type FileDescriptor = typing.Annotated[int, ValueRange(0, resource.RLIMIT_NOFILE)]
