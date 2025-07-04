import tempfile

import pytest

from linux.block.device import Sector, Disk
from linux.block.driver import Block


def test_sector():
    sector = Sector(id=0)
    b = bytearray(b"Hello world")
    # The sector should always remain the same size.
    with pytest.raises(ValueError):
        sector[:2] = b

    sector[:len(b)] = b
    assert sector[:len(b)] == b


def test_disk(disk: Disk):
    sector = Sector(id=0)
    b = bytearray(b"Hello world")
    sector[:len(b)] = b

    # Persist the sector from memory to disk.
    disk.write_sector(sector)
    assert disk.read_sector(id=sector.id) == sector
    assert disk.read_sector(id=sector.id) == sector, "Second read has to work as well."

    b = bytearray(b"Hopefully that world isn't Mars")
    sector[:len(b)] = b
    assert disk.read_sector(id=sector.id) != sector
    disk.write_sector(sector)
    assert disk.read_sector(id=sector.id) == sector


def test_disk_persist():
    with tempfile.NamedTemporaryFile(
        mode="r+b",
        buffering=0,
        delete_on_close=False,
    ) as f:
        # First persist some data.
        b = bytearray(b"Hello world")
        f.write(b)
        # Power up the machine, hopefully with the persisted data from
        # the previous boot.
        disk = Disk(pathname=f.name)
        sector = disk.read_sector(id=0)
        assert sector[:len(b)] == b


def test_block(disk: Disk):
    block = Block(sector_id=0, disk=disk)

    # A sector is just an in-memory construct. So unless it is written
    # to disk, it shouldn't impact a block.
    sector = Sector(id=0)
    b = bytearray(b"Hello world")
    sector[:len(b)] = b
    assert block[:len(b)] == bytearray(len(b))
    # Persist.
    disk.write_sector(sector)
    # Partial comparison.
    assert block[:len(b)] == sector[:len(b)]
    # Full comparison.
    assert block[:len(sector)] == sector

    b = bytearray(b"Hopefully that world isn't Mars")
    block.write(offset=0, value=b)
    assert block[:len(sector)] != sector, "In-memory sector should be unaffected."
    assert block[:len(b)] == b, "A read after a write should return the written data."

    b = bytearray(len(block) + 10)
    with pytest.raises(ValueError):
        block.write(offset=0, value=b)


def test_block_across_sectors(disk: Disk):
    block = Block(sector_id=0, disk=disk)

    s0 = Sector(id=0)
    s1 = Sector(id=1)
    s2 = Sector(id=2)
    assert len(block) >= len(s0) + len(s1) + len(s2)

    s0[-10:] = 10 * b"a"
    s1[:] = len(s1) * b"b"
    s2[10:20] = 10 * b"c"
    disk.write_sector(s0)
    disk.write_sector(s1)
    disk.write_sector(s2)

    start = len(s0) - 10
    stop = len(s0) + len(s1) + 20
    assert block[start:stop] == 10 * b"a" + len(s1) * b"b" + 10 * b"\x00" + 10 * b"c"
