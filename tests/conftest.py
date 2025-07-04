import tempfile

import pytest

from linux.block.device import Disk
from linux.block import BLOCK_SIZE
from linux.fs.super import SuperBlock


@pytest.fixture
def disk():
    with tempfile.NamedTemporaryFile(
        mode="r+b",
        buffering=0,
        delete_on_close=False,
    ) as f:
        size = 20 * BLOCK_SIZE
        disk = Disk(pathname=f.name, size=size)
        # Disk starts of nullified as per lseek(2).
        assert all(byte == 0x0 for byte in disk.read_sector(id=0))
        yield disk

@pytest.fixture
def super(disk):
    yield SuperBlock(disk=disk, format=True)
