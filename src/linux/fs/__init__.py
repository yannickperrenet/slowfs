from linux.block import BLOCK_SIZE

# In the kernel inodes have an `i_blkbits` attribute which we mimic with
# global constants.
INODE_SIZE = 256   # bytes
assert BLOCK_SIZE % INODE_SIZE == 0, (
    "Alignment won't work if block size is not a multiple."
)
