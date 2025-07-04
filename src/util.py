import typing

from linux.block.device import Disk
from linux.fs.super import SuperBlock
from linux.fs.vfs import VFS

# https://github.com/torvalds/linux/blob/master/arch/x86/entry/syscalls/syscall_64.tbl
# In the kernel there would actually be a mapping from integers to the
# name of the system call. However, since we don't need to write to and
# read from CPU registers we simply map the name of the system call to
# the appropriate function in a kernel component (only VFS in our case)
# that would be in charge of executing it.
def start_kernel(vfs: type[VFS]) -> dict[str, typing.Callable]:
    """Mimic running a kernel.

    Takes in the different kernel components and outputs the system
    calls that userspace can invoke.

    """
    i_vfs = vfs()

    return {
        "open": i_vfs.open,
        "close": i_vfs.close,
        "write": i_vfs.write,
        "read": i_vfs.read,
        "seek": i_vfs.seek,
        "mkdir": i_vfs.mkdir,
        "mount": i_vfs.mount,
        "umount": i_vfs.umount,
        "sysfs": i_vfs.sysfs,
    }


def mkfs_slowfs(disk: Disk) -> None:
    """Build the slowfs filesystem on the given disk.

    mkfs.<type> util. See: `man mkfs.ext4`.

    """
    super = SuperBlock(disk=disk, format=True)
    super.sync_fs()
    return
