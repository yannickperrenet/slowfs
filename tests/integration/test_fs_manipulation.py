import errno
import os

import util
from linux.block import BLOCK_SIZE
from linux.block.device import Disk
from linux.fs.vfs import VFS
from linux.sched import Process


def test_dir_structure(disk: Disk):
    # Set up filesystem.
    syscall_tbl = util.start_kernel(vfs=VFS)
    util.mkfs_slowfs(disk=disk)
    sudo = Process(syscall_tbl)
    sudo.mount(disk, "/mountpath")

    # Operate on a regular file.
    proc = Process(syscall_tbl)
    fd = proc.open(
        pathname="/mountpath/file1",
        flags=os.O_CREAT | os.O_RDWR,
        mode=0o644,
    )
    assert fd >= 0, "File creation failed."
    proc.write(fd, b"Hello world")
    proc.seek(fd, 0)
    assert proc.read(fd, 11) == b"Hello world"
    proc.seek(fd, 6)
    assert proc.read(fd, 5) == b"world"

    # Operate on a subdirectory and file in it.
    proc.mkdir(
        pathname="/mountpath/mydir",
    )
    fd2 = proc.open(
        pathname="/mountpath/mydir/file_in_dir",
        flags=os.O_CREAT | os.O_RDWR,
        mode=0o644,
    )
    assert fd2 == fd + 1, "Use lowest unused int for new file descriptor"
    proc.write(fd2, b"Im in a subdir")
    assert proc.read(fd2, 15) == b""
    proc.seek(fd2, 0)
    assert proc.read(fd2, 15) == b"Im in a subdir"

    # Write accross multiple blocks.
    proc.seek(fd, 0)
    data = BLOCK_SIZE * b"a" + BLOCK_SIZE * b"b" + BLOCK_SIZE * b"c"
    proc.write(fd, data)
    proc.seek(fd, 0)
    assert proc.read(fd, len(data)) == bytearray(data)

    proc.close(fd)
    proc.close(fd2)
    assert proc.read(fd, 15) == -errno.EBADF, "fd already closed"
    assert proc.read(fd2, 15) == -errno.EBADF, "fd already closed"

    # Persistence testing. Is everything still there?
    # Umount to trigger fsync()
    sudo.umount("/mountpath")
    sudo.mount(disk, "/mountpath")

    # How about the subdirectory?
    proc = Process(syscall_tbl)
    fd = proc.open(
        pathname="/mountpath/mydir/file_in_dir",
        flags=os.O_RDWR,
        mode=0o644,
    )
    assert fd >= 0
    assert proc.read(fd, 15) == b"Im in a subdir"
    proc.close(fd)

    # And the multi-block regular file?
    fd = proc.open(
        pathname="/mountpath/file1",
        flags=os.O_RDWR,
        mode=0o644,
    )
    assert fd >= 0
    assert proc.read(fd, len(data)) == bytearray(data)
