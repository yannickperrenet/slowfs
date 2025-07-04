import io
import os
import typing
from contextlib import contextmanager

from linux.block import SECTOR_SIZE

if typing.TYPE_CHECKING:
    from linux.types import Byte


class Sector:
    """In-memory structure to operate on physical block device sectors.

    This is the smallest atomic unit of a disk. Meaning that all reads
    and writes can't operate on a unit smaller than a sector.

    This object will store the data once it is read from the underlying
    block device and before writing it. This ensures that the block
    device is always presented with complete sectors (as it can't write
    partial sectors).

    This gives the block device driver an interface to work with.

    """
    __slots__ = ["id", "data", "_data"]

    def __init__(self, id: int, data: bytearray | None = None):
        self.id = id
        self._data = bytearray(SECTOR_SIZE)
        # Use memoryview to prevent resizing the underlying data.
        self.data = memoryview(self._data)
        if data is not None:
            self.data[:] = data

    def __iter__(self) -> typing.Iterator[int]:
        yield from self.data

    def __buffer__(self, flags: int, /) -> memoryview:
        return self.data.__buffer__(flags)

    def __len__(self) -> int:
        return SECTOR_SIZE

    @typing.overload
    def __getitem__(self, offset: int) -> "Byte": ...
    @typing.overload
    def __getitem__(self, offset: slice) -> memoryview: ...
    def __getitem__(self, offset: int | slice ) -> "Byte | memoryview":
        """Returns the bytes at `offset`."""
        if isinstance(offset, int):
            if offset >= SECTOR_SIZE:
                raise IndexError("Tried to index outside of sector.")

        return self.data[offset]

    @typing.overload
    def __setitem__(self, offset: int, value: int) -> None: ...
    @typing.overload
    def __setitem__(
        self,
        offset: slice,
        value: bytes | bytearray | memoryview,
    ) -> None: ...
    def __setitem__(
        self,
        offset: int | slice,
        value: int | bytes | bytearray | memoryview,
    ) -> None:
        # Annoying that we actually need these if statements to make the
        # type checker happy. The code is exactly the same in both cases
        # of the overload...
        if isinstance(offset, int) and isinstance(value, int):
            self.data[offset] = value
        elif isinstance(offset, slice) and isinstance(value, (bytes, bytearray, memoryview)):
            self.data[offset] = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sector):
            if self.id != other.id:
                return False
            return self.data == other.data
        else:
            return self.data == other


class Disk:
    """Block device.

    The linux kernel interacts with disk through a device driver that
    allows to operate on sectors. The device driver would write to the
    registers of the block device in order to operate on it.

    To mimic persisting data in this class we need underlying file
    storage which is passed through the `storage` argument.

    Arguments:
        pathname: Path to underlying file that stores our disk's data.
        size: Size of disk in bytes.

    """
    # TODO: Change size into size but in sectors instead of bytes.
    def __init__(self, pathname: str, size: int = 688128):
        # If the disk size is not a multiple of SECTOR_SIZE then those
        # bytes will not be exposed to any user of the disk.
        self.num_sectors = size // SECTOR_SIZE
        self.sector_size = SECTOR_SIZE
        if not os.path.exists(pathname):
            raise ValueError(f"Given path does not exist: {pathname}")
        self._pathname = pathname

    @contextmanager
    def storage(self) -> typing.Generator[io.FileIO, None, None]:
        with open(self._pathname, "r+b", buffering=0) as f:
            yield f

    def read_sector(self, id: int) -> Sector:
        """Read sector from disk into memory.

        Returns:
            An in-memory structure of a sector. The kernel would copy
            the bytes representing a sector from the disk and store
            them in memory for reads (and writes).

        """
        if id >= self.num_sectors:
            raise IndexError("Sector does not exist on this disk.")

        offset = id * SECTOR_SIZE
        # Allocate memory buffer.
        sector = Sector(id)
        with self.storage() as storage:
            storage.seek(offset)
            storage.readinto(sector)
        return sector

    def write_sector(self, sector: Sector) -> None:
        """Write sector to disk.

        Disks expect data to be send to them in entire sectors.

        From an implementation perspective, by expecting a Sector object
        we are ensured the disk can always write it to an underlying
        sector on the disk itself.

        """
        if sector.id >= self.num_sectors:
            raise IndexError("Sector does not exist on this disk.")

        offset = sector.id * SECTOR_SIZE
        with self.storage() as storage:
            storage.seek(offset)
            storage.write(sector)
