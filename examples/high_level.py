import errno
import os

from linux.block.device import Disk
from linux.fs.vfs import VFS
from linux.sched import Process

import util


def create_slowfs_blockdev(pathname: str) -> Disk:
    """Create the slowfs filesystem in a file at pathname.

    Note, block devices are just files in Linux.

    Returns a block device object on top of the file at pathname.

    """
    if not os.path.exists(pathname):
        fname = os.path.basename(pathname)
        path = pathname.removesuffix(fname)
        os.makedirs(path, exist_ok=True)
        with open(pathname, "w") as _: ...

    disk = Disk(pathname)
    util.mkfs_slowfs(disk=disk)
    return disk


if __name__ == "__main__":
    # Path to file to store filesystem in. Inspect the local file for
    # yourself to see the bytes that represent the filesystem.
    storage_path = "tmp/slowfs.raw"
    # Simulate having a block device with the slowfs file system on it.
    disk = create_slowfs_blockdev(storage_path)
    # Interface for userspace processes to interact with the kernel.
    syscall_tbl = util.start_kernel(vfs=VFS)

    # Create a process and give it access to the full system call
    # table, i.e. allowing it to run every system call.
    sudo = Process(syscall_tbl)
    sudo.mount(disk, "/mountpoint")

    # NOTE: We could've given only a subset of the system calls to this
    # process to mimic security.
    proc = Process(syscall_tbl)
    fd = proc.open(
        pathname="/mountpoint/file",
        # If the file doesn't exist, then create it. Open it in
        # read/write access mode.
        flags=os.O_CREAT | os.O_RDWR,
        # File mode bits to be applied when a new file is created.
        mode=0o644,
    )
    assert fd >= 0
    proc.write(fd, b"Hello world")
    proc.seek(fd, 0)
    assert proc.read(fd, 11) == b"Hello world"
    assert proc.read(fd, 2) == b""
    proc.seek(fd, 6)
    assert proc.read(fd, 5) == b"world"
    assert proc.close(fd) == 0

    # We can also create subdirectories and files within them.
    proc.mkdir(
        pathname="/mountpoint/mydir",
    )
    fd = proc.open(
        pathname="/mountpoint/mydir/file",
        flags=os.O_CREAT | os.O_RDWR,
        mode=0o644,
    )
    proc.write(fd, b"Im in a subdir")
    proc.seek(fd, 0)
    assert proc.read(fd, 15) == b"Im in a subdir"
    proc.close(fd)

    fd = proc.open(
        pathname="/mountpoint/not_a_subdir/file",
        flags=os.O_CREAT | os.O_RDWR,
        mode=0o644,
    )
    assert fd == -errno.ENOENT, "The subdirectory shouldn't exist."
    proc.close(fd)

    # Sync dirty filesystem state to disk on unmount.
    sudo.umount("/mountpoint")

    # Check whether state was correctly persisted.
    disk = Disk(storage_path)
    sudo.mount(disk, "/my-mnt")
    fd = sudo.open(
        pathname="/my-mnt/mydir/file",
        flags=os.O_RDONLY,
        mode=0o644,
    )
    assert fd >= 0
    assert sudo.read(fd, 15) == b"Im in a subdir"
    sudo.close(fd)
