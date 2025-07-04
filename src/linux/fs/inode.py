import errno
import stat
import struct
import typing

from linux.block import BLOCK_SIZE
from linux.fs import INODE_SIZE

if typing.TYPE_CHECKING:
    from linux.fs.super import SuperBlock
    from linux.block.driver import Block

    class Length(typing.NamedTuple):
        value: int

    type InodeBytes = typing.Annotated[bytes, Length(INODE_SIZE)]


# Serialization of an inode.
#
# Attributes that don't have to be included:
#
# sb:       Will be done in superblock init so object is passed
#
# Attributes:
#
# i_ino:        32 bit = 4 bytes
# i_mode:       32 bit
# i_size:       32 bit
# num_f_in_dir: 32 bit
# p_ino:        32 bit
# blocks:       only the ids, 32 bit per id
#
# So the maximum amount of blocks will be:
# INODE_SIZE = 256 bytes
# 256 - 5*4 = 236 bytes
# -> 236 / 4 = 59 blocks
#
# NOTE: Thus the largest file we support is 59 * BLOCK_SIZE.
_MAX_DBLOCKS = 59
# NOTE: It is important that ID < 0, because inode storage is not
# guaranteed to be nullified on removal and positive IDs are reserved
# for in use dblocks.
_FREE_DBLOCK_ID = -1
_INODE_LAYOUT = f">IIIII{_MAX_DBLOCKS}i"

# Serialization to store directory contents on disk.
#
# This is the format to store the file and subdirectory names, with
# corresponding inodes, that are put in a directory within the data
# block of a directory.
#
# Let's fit the metadata for 1 entry into 256 bits:
#
# ino:          32 bit, where 0 indicates no file.
# name_len:     8 bit
# name:         (1 << 8) - 1 = 255 bytes at most
#
# NOTE: The name can actually be at most 27 bytes as otherwise the 32
# bytes limit for the layout would be exceeded.
_MAX_FNAME_LEN = 27
_DIR_LAYOUT = f">IB{_MAX_FNAME_LEN}s"
_DIR_LAYOUT_SIZE = 32  # bytes
assert BLOCK_SIZE % _DIR_LAYOUT_SIZE == 0, (
    "Inode directory structure doesn't fit cleanly in a block."
)

# https://github.com/torvalds/linux/blob/fe78e02600f83d81e55f6fc352d82c4f264a2901/include/linux/fs.h#L674
# Also see: `man inode`
#
# NOTE: The name of the file the inode points to is not included in the
# inode struct itself. Filenames are stored in the directory structure.
class Inode:
    def __init__(
        self,
        sb: "SuperBlock",
        ino: int,
        mode: int = 0,
        size: int = 0,
        num_f_in_dir: int = 0,
        blocks: "list[tuple[int, Block]] | None" = None,
        p_ino: int = -1,
    ):
        # Points to superblock the inode is part of. By maintaining a
        # pointer, we can access superblock methods directly.
        self.i_sb = sb
        # Unique inode number.
        self.i_ino = ino
        # Integer representing the file type, file mode bits and file
        # permission bits. See: `man inode`
        self.i_mode = mode
        # Size in bytes of underlying file. Among other things, needed
        # to move the file offset to the end in case of O_APPEND mode.
        self.i_size = size
        self.i_uid = 1000
        self.i_gid = 1000
        # Blocks that store the data of the file of this inode.
        #
        # tuple[int, Block] so we know the id in the sb.dmap where
        # the block is stored. Needed for persisting the inode,
        # otherwise we can't restore the data the inode points to.
        #
        # TODO: Maybe a list of ints is better? The Block could store
        # the id. Similarly, we could get the block from the id.
        if blocks is None:
            self.blocks: "list[tuple[int, Block]]" = []
        else:
            self.blocks = blocks

        # ----
        # Attributes specific to our implementation of an inode.
        # ----
        # In the kernel, there is an attribute pointing to the dentry.
        # Instead we just point to the parent directory inode in order
        # to insert pathnames into it.
        self.p_ino: int = p_ino
        # To make it easier to add new files to directories.
        self.num_f_in_dir = num_f_in_dir

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Inode):
            return bytes(self) == bytes(other)
        return False

    def __bytes__(self) -> "InodeBytes":
        """Serialize inode to bytes."""
        assert self.p_ino >= 0, "Forgot to set p_ino on inode"
        # Although data blocks should only be allocated through
        # self.alloc_dblocks(), let's make sure we indeed did.
        n = len(self.blocks)
        assert n <= _MAX_DBLOCKS, "Max number of data blocks exceeded."

        # Pad ids with non-existing id number.
        block_ids = [id for id, _ in self.blocks] + (59 - n) * [_FREE_DBLOCK_ID]
        return struct.pack(
            _INODE_LAYOUT,
            self.i_ino,
            self.i_mode,
            self.i_size,
            self.num_f_in_dir,
            self.p_ino,
            *block_ids
        )

    @classmethod
    def from_bytes(cls, b: bytearray | bytes, sb: "SuperBlock") -> "Inode":
        """Deserialize inode from bytes."""
        # See: `self.__bytes__()`
        # We need to deserialize according to the serialization.
        (
            ino,
            mode,
            size,
            num_f_in_dir,
            p_ino,
            *block_ids
        ) = struct.unpack(_INODE_LAYOUT, b)
        blocks = [(id, sb.dzone[id]) for id in block_ids if id != _FREE_DBLOCK_ID]
        return Inode(
            sb=sb,
            ino=ino,
            mode=mode,
            size=size,
            num_f_in_dir=num_f_in_dir,
            blocks=blocks,
            p_ino=p_ino,
        )

    @staticmethod
    def lookup(pathname: str, sb: "SuperBlock") -> "tuple[int, Inode]":
        """Lookup an inode in a parent directory, recursively.

        Since we don't have support for the dentry cache, we instead
        also return the inode of the closest ancestor directory. This
        is useful in the case where the pathname doesn't exist yet and
        we want to create it, i.e. add it to the closest ancestor.

        Arguments:
            pathname: Must be prefixed with `/`, consist only of ASCII
                characters and not exceed the maximum length of
                _MAX_FNAME_LEN characters for any of the directories or
                filenames in the path.
            superblock: Superblock to be searched.

        Returns:
            0, Inode: if pathname was found, where Inode is the
                found inode.
            -1, Inode: if pathname was not found, where inode is
                the parent inode.
            -2, Inode: if pathname was not found and there were missing
                subdirectories. Where inode is closest ancestor
                directory inode that existed.
            -ENODEV, root: if pathname not even on superblock device.
            -EINVAL, root: if pathname contains characters that aren't
                permitted or it contains a component that exceeds the
                maximum name length.

        """
        assert not ({errno.ENODEV, errno.EINVAL} & {0, -1, -2}), "Error codes overlap"

        if not pathname.startswith("/"):
            # Not even in superblock root.
            return -errno.ENODEV, sb.root
        elif pathname == "/":
            return 0, sb.root
        else:
            pathname = pathname.removeprefix("/")

        components = pathname.split("/")
        if any(not _is_valid_path_component(c) for c in components):
            return -errno.EINVAL, sb.root

        p_inode = sb.root
        for i, component in enumerate(components):
            c_as_bytes = component.encode("ascii")
            found_component = False
            for _, block in p_inode.blocks:
                for ino, name in _deserialize_dir_content(block):
                    if ino == 0:
                        # The ino=0 is reserved and indicates that the
                        # entry is empty. In case one would like to
                        # implement reusing old state within a directory
                        # we would have to use a special thombstone
                        # value.
                        break

                    if name == c_as_bytes:
                        found_component = True
                        if ino in sb.inodes:
                            p_inode = sb.inodes[ino]
                        else:
                            p_inode = sb.read_inode_from_disk(ino=ino)
                        break

                if found_component:
                    break

            if not found_component:
                # errno.ENOENT should actually be used in both cases,
                # but that doesn't allow us to differentiate between
                # them.
                if i+1 == len(components):
                    # All subdirectories exist, just the final component
                    # doesn't.
                    return -1, p_inode
                else:
                    # Directory component in pathname doesn't exist.
                    return -2, p_inode

        return 0, p_inode

    def create(self, p_inode: "Inode | None" = None, mode: int = 0o666) -> int:
        """Create a regular file."""
        # See: inode(7) at "file type and mode"
        assert not stat.S_ISDIR(self.i_mode), (
            "Can't change existing inode into regular file."
        )
        assert p_inode is not None or self.p_ino != -1, (
            "Parent inode has to be known to link new inode to it."
        )

        if p_inode is not None:
            self.p_ino = p_inode.i_ino
        # Set file type and permissions
        # Permissions can also be set with e.g.:
        #   `S_IRWXU | S_IRGRP | S_IROTH`
        self.i_mode = stat.S_IFREG | mode
        return 0

    def unlink(self) -> int:
        """Delete an inode."""
        return 0

    def mkdir(self, mode: int = 0o555) -> int:
        """Called by mkdir(2) system call."""
        assert not stat.S_ISREG(self.i_mode), (
            "Can't change existing inode into directory."
        )
        assert self.p_ino >= 0, "Forgot to set p_ino on inode."

        # For more info see: self.create()
        self.i_mode = stat.S_IFDIR | mode

        block = self.i_sb.alloc_dblocks(1)
        if not block:
            return -errno.ENOSPC
        self.blocks.extend(block)
        self.i_size = BLOCK_SIZE
        # These components are always included in directories.
        self.add_dir_entry(".", self)
        self.add_dir_entry("..", self.i_sb.inodes[self.p_ino])

        return 0

    # TODO: ...
    # TODO: Also deletes the underlying inode.
    # TODO: Actually delete the directory -> likely happens in
    # another struct.
    # TODO: Should remove the directory name from the parent
    # directory.
    def rmdir(self) -> int:
        if not stat.S_ISDIR(self.i_mode):
            return -errno.ENOTDIR
        return 0

    # TODO: ...
    def permission(self) -> int:
        return self.i_mode & 0o777

    # TODO: ...
    def getattr(self) -> int:
        # Used for stat(2).
        return 0

    # TODO: ...
    def setattr(self) -> int:
        return 0

    def __repr__(self):
        return f"Inode(ino={self.i_ino}, mode={self.i_mode})"

    # ----
    # Methods to make our implementation work.
    # ----

    def add_dir_entry(self, fname: str, inode: "Inode") -> int:
        """Add the given `inode` to the directory `self` under `fname`."""
        # Can only add to a directory.
        if not stat.S_ISDIR(self.i_mode):
            raise ValueError("`self` has to be a directory.")

        if not _is_valid_path_component(fname):
            return -errno.EINVAL

        b, offset = divmod(self.num_f_in_dir * _DIR_LAYOUT_SIZE, BLOCK_SIZE)
        if b >= len(self.blocks):
            err = self.alloc_dblocks(1)
            if err != 0:
                return err

        name = fname.encode("ascii")
        data = struct.pack(_DIR_LAYOUT, inode.i_ino, len(name), name)
        _, block = self.blocks[b]
        block.write(offset, data)

        self.num_f_in_dir += 1
        return 0

    def alloc_dblocks(self, count: int) -> int:
        """Allocate `count` data blocks for this inode."""
        if count > _MAX_DBLOCKS - len(self.blocks):
            # Maximum amount of data blocks exceeded. The inode can only
            # store a max amount of data block pointers, since it has to
            # conform to the _INODE_LAYOUT.
            return -errno.ENOSPC

        dblocks = self.i_sb.alloc_dblocks(count)
        if not dblocks:
            return -errno.ENOSPC
        self.blocks.extend(dblocks)

        # Directory can grow beyond `BLOCK_SIZE` if it contains many
        # files.
        if stat.S_ISDIR(self.i_mode):
            self.i_size += BLOCK_SIZE

        return 0


def _deserialize_dir_content(
    block: "Block",
) -> typing.Generator[tuple[int, bytes], None, None]:
    """Generator over entries in a directory block."""
    for offset in range(0, BLOCK_SIZE, _DIR_LAYOUT_SIZE):
        (
            ino,
            name_len,
            name
        ) = struct.unpack(_DIR_LAYOUT, block[offset:offset+_DIR_LAYOUT_SIZE])
        name = name[:name_len]
        yield (ino, name)


def _is_valid_path_component(name: str) -> bool:
    """Check whether the given name is a valid component in a path."""
    return (
        name.isascii()
        # Uses the fact that 1 ASCII char takes exactly 1 byte.
        and len(name) <= _MAX_FNAME_LEN
        and "/" not in name
    )
