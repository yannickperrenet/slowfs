import contextlib
import typing

from linux.block import BLOCK_SIZE
from linux.block.driver import Block
from linux.fs import INODE_SIZE
from linux.fs.inode import Inode

if typing.TYPE_CHECKING:
    from linux.block.device import Disk


class BitMap:
    """Store integers in the map as a single bit in a sequence of bytes.

    More well known as a bitset.

    Lays out a sequence of bytes where the individual bits are 0 if the
    item is not present and 1 otherwise.

    Arguments:
        size: Number of bytes for the underlying sequence of bytes.

    """
    def __init__(self, size: int = 0):
        self.size = size
        self.data = bytearray(self.size)

        # The bits are layed out as follows:
        # 76543210 76543210 ...

    def next_free(self) -> int:
        """Return the first unused index.

        Returns -1 in case the bitmap is fully used.

        """
        i = 0
        for byte in self.data:
            for j in range(8):
                if byte & (1 << j):
                    i += 1
                else:
                    return i
        return -1

    @classmethod
    def from_block(cls, block: Block) -> "BitMap":
        bm = cls(size=BLOCK_SIZE)
        bm.data[:] = block[:]
        return bm

    def alloc(self, i: int) -> None:
        """Allocate index i, marking it as used. Idempotent."""
        if i < 0:
            raise ValueError("Only positive indices are allowed.")

        b, res = divmod(i, 8)
        assert self.data[b] & (1 << res) == 0, "Bit already allocated."
        self.data[b] ^= 1 << res

    def free(self, i: int) -> None:
        """Free an index (idempotent)."""
        if i < 0:
            raise ValueError("Only positive indices are allowed.")

        b, res = divmod(i, 8)
        # 1s with a zero where we want to free, e.g. 11101111
        mask = ((1 << 8) - 1) ^ (1 << res)
        self.data[b] &= mask

    def __iter__(self) -> typing.Iterator[int]:
        """Iterate over all allocated indices."""
        i = 0
        for byte in self.data:
            for j in range(8):
                if byte & (1 << j):
                    yield i
                i += 1

    def __buffer__(self, flags: int, /) -> memoryview:
        return self.data.__buffer__(flags)


# https://litux.nl/mirror/kerneldevelopment/0672327201/ch12lev1sec5.html
class SuperBlock:
    """A superblock object to represent a mounted filesystem.

    This descibes how the VFS can manipulate the superblock of the
    filesystem.

    This object contains information about the filesystem, e.g. where
    the inode table begins.

    Args:
        disk: The block device on which the superblock lives.
        format: True if the block device should be formatted to use this
            filesystem, False if the superblock should be initialized
            from the block device.

    """
    def __init__(self, disk: "Disk", format: bool = False):
        # Superblock identifier.
        # Used to check whether this filesystem is written on a disk.
        self.fs_type = 137
        assert self.fs_type < (1 << 8), "Superblock identifier should fit in one byte"

        # Divide the disk into blocks by assigning sectors.
        # NOTE: If there is a remainder, then those sectors won't
        # be included in blocks.
        sector_size = disk.sector_size
        num_blocks = disk.num_sectors // (BLOCK_SIZE // sector_size)
        if num_blocks < 5:
            # At least one block for each of:
            # superblock, imap, dmap, izone, dzone
            raise ValueError("Disk too small to fit fileystem.")
        bsize_in_sectors = BLOCK_SIZE // sector_size
        self.blocks = tuple(
            Block(sector_id=i*bsize_in_sectors, disk=disk)
            for i in range(num_blocks)
        )

        # TODO: Improve performance by only reading the first block for
        # this check.
        #
        # Check whether superblock identifier is present.
        if not format and self.blocks[0][0] != self.fs_type:
            raise ValueError(
                "The given disk does not contain filesystem of"
                f"type slowfs({self.fs_type})."
            )

        # Let's say we have built a filesystem that works best for the
        # following workload:
        # 1 inode : 2 data blocks  (on average)
        #   meaning that the average file size is 2 * BLOCK_SIZE
        # Of course, in that case we could've opted for smaller
        # INODE_SIZE so we can pack more inodes in a block, but this is
        # not a filesystem intended to be used in production and we
        # are after learning about filesystems here :)
        N = num_blocks - 3  # blocks left to divide of izone and dzone.
        izone_size = max(N // 3, 1)
        # NOTE: The items in these slices point to the same underlying
        # blocks, i.e. no deepcopy is created.
        self.izone = self.blocks[3:3+izone_size]
        self.dzone = self.blocks[3+izone_size:3+N]

        # Keep all inodes in memory to support opening a file multiple
        # times as well as making self.lookup() faster by reading inodes
        # from memory instead of disk.
        # TODO: In the future don't read in all inodes as that takes
        # a lot of memory. Just populate it as we go, e.g. LRU.
        # https://linux-kernel-labs.github.io/refs/heads/master/lectures/fs.html#the-inode-cache
        # TODO: This map could become a special object that takes care
        # of eviction so individual methods don't have to take it into
        # account.
        self.inodes: dict[int, Inode] = {}

        if not format:
            self._init_from_disk()
        else:
            self.imap = BitMap(BLOCK_SIZE)
            self.dmap = BitMap(BLOCK_SIZE)

            # Hacky solution to always make sure the 0th inode is allocated.
            # This is handy because we nullify blocks and thus can treat a
            # zero byte as special, because no inode will ever have ino=0.
            with contextlib.suppress(AssertionError):
                self.imap.alloc(0)

            # From this root inode we will get a linked structure to all
            # other inodes we have.
            #
            # NOTE: First assign the result of alloc_inode() into a
            # variable before assigning it (after checking for None) to
            # self.root. This makes sure the type checker understands
            # that self.root is always assigned a type of Inode.
            root = self.alloc_inode()
            if root is None:
                raise ValueError("Disk size too small to fit inode table.")
            self.root = root
            self.root.p_ino = self.root.i_ino  # point to itself
            self.root.mkdir()
            self.inodes[self.root.i_ino] = self.root

        # Quick check whether initializing the superblock from disk or
        # from scratch yield the same attributes.
        assert hasattr(self, "imap") and hasattr(self, "dmap") and hasattr(self, "root")

        # The filesystem will never fully utilize the disk, because more
        # data blocks and inodes could be created than can be tracked by
        # the filesystem.
        if self.imap.size < len(self.izone) * (BLOCK_SIZE // INODE_SIZE):
            # imap size too small to allow utilizing all inodes.
            ...
        if self.dmap.size < len(self.dzone):
            ...

    def alloc_inode(self) -> Inode | None:
        """Allocate an inode."""
        # Since we are single threaded we can assume that allocating an
        # inode always succeeds, because if it doesn't then the state
        # change would never hit disk. And thus the imap entry change is
        # also never recorded.
        # Otherwise the imap entry would've remained allocated
        # indefinitely even though the inode is not in use.

        i = self.imap.next_free()
        if i == -1:
            # imap is full.
            return None
        elif i >= len(self.izone) * (BLOCK_SIZE // INODE_SIZE):
            # No free inodes left.
            # If all inodes of a system are occupied, then the system
            # could no longer run. Because in Linux everything is a
            # file.
            return None

        self.imap.alloc(i)
        inode = Inode(sb=self, ino=i)
        self.inodes[i] = inode
        return inode

    def write_inode(self, inode: Inode) -> None:
        """Persist inode to storage medium."""
        i = inode.i_ino
        inodes_per_block = BLOCK_SIZE // INODE_SIZE
        b, offset = divmod(i, inodes_per_block)
        offset *= INODE_SIZE

        # Write inode to block at offset
        block = self.izone[b]
        block.write(offset, bytes(inode))

    def sync_fs(self) -> int:
        """Write out all dirty data associated with this superblock."""
        # Since we don't dirty any state when changing it, we assume all
        # state is dirty.
        #
        # Attributes:
        #
        # superblock
        # imap
        # dmap
        # izone
        # dzone         -> already persisted
        #
        # Since we don't have to integrate with the Linux kernel, we can
        # decide ourselves what state of the superblock we need to write
        # to disk in order for the SuperBlock.__init__() to work.

        # Indicate the superblock should load state from disk.
        # NOTE: fs_type Fits in single byte so endianness has no impact.
        sblock = self.blocks[0]
        sblock.write(0, self.fs_type.to_bytes())
        # Write imap and dmap into the following two blocks.
        iblock = self.blocks[1]
        iblock.write(0, memoryview(self.imap))
        dblock = self.blocks[2]
        dblock.write(0, memoryview(self.dmap))
        # Persist all inodes. All dirty inodes are in memory.
        for _, inode in self.inodes.items():
            self.write_inode(inode)

        return 0

    # TODO: ...
    def destroy_inode(self, inode: Inode) -> None:
        """Release inode resources.

        Note:
            Does not nullify inode storage since indicating that the
            inode is no longer occupied (i.e. imap[i_no] = 0) should
            be enough.

        """
        i = inode.i_ino
        # TODO: Release resources, imap and corresponding dzone.
        ...
        self.imap.free(i=i)

    # ----
    # Methods to get everything working
    # ----
    #
    # These method would probably live in different sections in the
    # Linux kernel, but are put here for convenience.

    # Probably usually a block allocater.
    def alloc_dblocks(
        self,
        count: int,
    ) -> list[tuple[int, Block]]:
        """Allocate count number of data blocks.

        Returns:
            The allocated data blocks if count blocks were still free.

            Otherwise no blocks are returned to indicate that there was
            not enough space.

        """
        blocks = []
        for _ in range(count):
            i = self.dmap.next_free()
            if i == -1:
                # dmap is full
                break
            elif i >= len(self.dzone):
                # No more blocks available.
                break
            self.dmap.alloc(i)
            blocks.append((i, self.dzone[i]))

        if len(blocks) == count:
            # Nullify each block so there is no stale data left.
            # Otherwise we could hit the case where a new directory is
            # created but it points to a deleted directory data block
            # and thereby suddenly having subdirectories and files in
            # it.
            for _, block in blocks:
                block.write(0, len(block) * b"\x00")
            return blocks

        # Not enough space left, so deallocate the blocks.
        for i, _ in blocks:
            self.dmap.free(i)
        return []

    def dealloc_dblocks(self, blocks: list[tuple[int, Block]]) -> None:
        for i, _ in blocks:
            self.dmap.free(i)

    def read_inode_from_disk(self, ino: int) -> Inode:
        # TODO: When do we want to store the inode from disk in memory?
        #   In self.inodes that is.
        inodes_per_block = BLOCK_SIZE // INODE_SIZE
        b, offset = divmod(ino, inodes_per_block)
        offset *= INODE_SIZE
        block = self.izone[b]
        return Inode.from_bytes(
            b=block[offset:offset+INODE_SIZE],
            sb=self,
        )

    def _init_from_disk(self) -> None:
        self.imap = BitMap.from_block(self.blocks[1])
        self.dmap = BitMap.from_block(self.blocks[2])
        # TODO: How do actual file systems make this more performant?
        #   Since they support many more inodes, I'm sure they don't
        #   have to loop over everything or they simply initialize
        #   only the first X inodes.
        for i in self.imap:
            inode = self.read_inode_from_disk(ino=i)
            self.inodes[inode.i_ino] = inode

        # Root node for linked file structure.
        # NOTE: We always know it is the second inode, because the first
        # is left empty by the imap.
        self.root = Inode.from_bytes(
            b=self.izone[0][INODE_SIZE:2*INODE_SIZE],
            sb=self,
        )
        self.inodes[self.root.i_ino] = self.root
