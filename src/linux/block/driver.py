import typing

from linux.block import BLOCK_SIZE, SECTOR_SIZE
from linux.block.device import Sector

if typing.TYPE_CHECKING:
    from linux.block.device import Disk
    from linux.types import Byte


class Block:
    """Block device driver.

    Acts as a device driver to interact with a block device. Meaning
    that the kernel uses this driver to read and write to a block
    device.

    In the Linux kernel a device driver could expose more functionality
    for the kernel to optimize disk interactions. For example, the
    kernel groups block requests together that access contiguous blocks.

    Moreover, the kernel doesn't operate on any unit smaller than
    blocks. As that is the interface it is given.

    Arguments:
        sector_id: The first disk sector of this block. Other sectors in
            this block can be obtained through offsetting.
        disk: The disk (block device) of which this block is the device
            driver.

    """
    __slots__ = ["sector_id", "disk"]

    def __init__(self, sector_id: int, disk: "Disk"):
        self.sector_id = sector_id
        self.disk = disk

    # https://docs.python.org/3/reference/datamodel.html#object.__getitem__
    @typing.overload
    def __getitem__(self, key: int) -> "Byte": ...
    @typing.overload
    def __getitem__(self, key: slice) -> bytearray: ...
    def __getitem__(self, key: int | slice) -> "Byte | bytearray":
        if isinstance(key, int):
            assert key <= BLOCK_SIZE, "Block doesn't contain byte."

            s, res = divmod(key, SECTOR_SIZE)
            sector = self.disk.read_sector(id=self.sector_id+s)
            return sector[res]

        else:
            start, stop = key.start or 0, key.stop or BLOCK_SIZE

            # Didn't feel like writing a single pass implementation for
            # slices.
            if key.step is not None or start < 0 or stop < 0:
                raise NotImplementedError("Slice final data yourself.")

            # TODO: Can't I come up with better code for this?
            n = min(BLOCK_SIZE, stop - start)
            buf = bytearray(n)
            ptr_buf = 0
            s, offset = divmod(start, SECTOR_SIZE)
            bsize_in_sectors = BLOCK_SIZE // SECTOR_SIZE
            for s in range(s, bsize_in_sectors):
                sector = self.disk.read_sector(id=self.sector_id+s)

                size = min(SECTOR_SIZE - offset, n - ptr_buf)
                buf[ptr_buf:ptr_buf+size] = sector[offset:offset+size]
                ptr_buf += size

                offset = 0
                if ptr_buf == n:
                    break

            return buf

    def __len__(self) -> int:
        return BLOCK_SIZE

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Block):
            return False

        if self.sector_id != other.sector_id:
            return False
        return self[:] == other[:]

    def __iter__(self) -> typing.Iterator[int]:
        """Iterate over bytes in the block in order."""
        bsize_in_sectors = BLOCK_SIZE // SECTOR_SIZE
        for s in range(bsize_in_sectors):
            sector = self.disk.read_sector(id=self.sector_id+s)
            yield from sector

    def write(
        self,
        offset: int,
        value: bytearray | bytes | memoryview,
    ) -> None:
        """Write a set of bytes into the block at offset."""
        # Create a memoryview to prevent slicing the value to create
        # an intermediary copy of the data. We want to copy the data
        # from the value into the sector, without creating an
        # additional copy.
        if not isinstance(value, memoryview):
            value = memoryview(value)

        n = len(value)
        if offset + n > BLOCK_SIZE:
            raise ValueError("Can't write past block size.")

        # Similar code is in File.write()
        s, offset = divmod(offset, SECTOR_SIZE)
        bsize_in_sectors = BLOCK_SIZE // SECTOR_SIZE
        ptr_buf = 0
        for s in range(s, bsize_in_sectors):
            size = min(SECTOR_SIZE - offset, n - ptr_buf)
            if offset == 0 and size == SECTOR_SIZE:
                sector = Sector(id=self.sector_id+s)
            else:
                # Note how we first need the sector to be read, even if
                # we only want to change it partially.
                sector = self.disk.read_sector(id=self.sector_id+s)

            sector[offset:offset+size] = value[ptr_buf:ptr_buf+size]
            self.disk.write_sector(sector)
            ptr_buf += size

            offset = 0
            if ptr_buf >= n:
                break
