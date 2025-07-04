# Sector size is specific to a block device.
SECTOR_SIZE = 512  # bytes
# The block size used throughout the linux kernel.
BLOCK_SIZE = 4096  # bytes

assert BLOCK_SIZE % SECTOR_SIZE == 0, "Complete sectors make up a block."
