import typing

from linux.block import BLOCK_SIZE
from linux.fs.super import SuperBlock
from linux.fs import INODE_SIZE

if typing.TYPE_CHECKING:
    from linux.block.device import Disk


# Yes, not the greatest test as it is an implementation detail.
def test_init(disk: "Disk"):
    super = SuperBlock(disk=disk, format=True)

    assert hasattr(super, "inodes"), "Alternative for dentry used by inodes"
    assert hasattr(super, "root"), "Used to lookup() an inode"


def test_alloc_inode(disk: "Disk"):
    super = SuperBlock(disk=disk, format=True)

    seen = set()
    while (inode := super.alloc_inode()) is not None:
        ino = inode.i_ino
        assert ino not in seen, "Never allocate the same inode."
        seen.add(ino)


def test_alloc_dblocks(disk: "Disk"):
    super = SuperBlock(disk=disk, format=True)

    num_blocks = disk.num_sectors * disk.sector_size // BLOCK_SIZE
    assert super.alloc_dblocks(count=2*num_blocks) == [], "Not enough space."

    seen = set()
    for _ in range(num_blocks):
        blocks = super.alloc_dblocks(count=1)
        for i, _ in blocks:
            assert i not in seen, "Never allocate the same data block."
            seen.add(i)

    assert len(seen) > 0, "Enough space to allocate at least 1 block."
    assert super.alloc_dblocks(count=1) == [], "Disk should be full now."


def test_sync_fs(disk: "Disk"):
    # Can we sync to disk and then initialize an existing fs again?
    super = SuperBlock(disk=disk, format=True)

    inodes_per_block = BLOCK_SIZE // INODE_SIZE
    assert inodes_per_block >= 4, "Otherwise the rest of the test makes no sense."

    seen = set()
    for _ in range(inodes_per_block - 2):
        inode = super.alloc_inode()
        assert inode is not None, "Inode should fit in block"
        seen.add(inode.i_ino)

        # Implementation specific
        assert hasattr(inode, "p_ino"), "Substitute for dentry cache"
        # Has to be set as otherwise the filesystem is in an invalid
        # state and can't be synced to disk.
        inode.p_ino = super.root.i_ino

    assert len(seen) == inodes_per_block - 2

    block_id, _ = super.alloc_dblocks(count=1)[0]
    assert super.sync_fs() == 0, "State successfully synced to disk."

    # Restore superblock from disk.
    super = SuperBlock(disk=disk)
    # Unique inodes.
    while (inode := super.alloc_inode()) is not None:
        ino = inode.i_ino
        assert ino not in seen, "Never allocate the same inode."
    # Unique data blocks.
    while (block := super.alloc_dblocks(count=1)):
        id, _ = block[0]
        assert id != block_id, "Never allocate the same data block."
