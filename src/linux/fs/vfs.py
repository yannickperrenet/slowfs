import errno
import stat
import typing
import os

from linux.fs.file import File
from linux.fs.inode import Inode
from linux.fs.super import SuperBlock
from linux.sched import Process

if typing.TYPE_CHECKING:
    from linux.block.device import Disk
    from linux.types import Err, FileDescriptor, ResultInt


class VFS:
    """Virtual File System.

    VFS is an abstraction that provides the filesystem interface to
    userspace programs.

    """
    def __init__(self) -> None:
        self.sblocks: dict[str, SuperBlock] = {}

    def sysfs(self) -> dict[str, SuperBlock]:
        """sysfs(2).

        This system call is actually deprecated, but we use it to give
        users a way to obtain superblock information on the system.

        """
        return self.sblocks

    def mount(self, blockdev: "Disk", mountpoint: str) -> "ResultInt":
        """Mount the block device at mountpoint. mount(2).

        Note:
            In the Linux kernel, block devices are also files, and
            thereby have an inode, and thus this method should actually
            take a source path. However, since we only support regular
            files and directories we use a block device object instead.

        Args:
            mounpoint: Absolute path indicating the location to mount
                the block device at.

        """
        if mountpoint in self.sblocks:
            raise ValueError(f"Another superblock is already mounted at: {mountpoint}")

        # Normally, the kernel would check what the filesystem type is,
        # but since we only have support for one, we initialize it
        # directly.
        sb = SuperBlock(disk=blockdev)
        self.sblocks[mountpoint] = sb
        return 0

    def umount(self, mountpoint: str) -> "ResultInt":
        """Unmount filesystem. umount(2)."""
        if (sb := self.sblocks.get(mountpoint)) is None:
            raise ValueError(f"Mountpoint not in use.")
        else:
            del self.sblocks[mountpoint]

        # Make sure all state is written to persistent storage.
        return sb.sync_fs()

    def open(
        self,
        pathname: str,
        flags: int,
        mode: int,
        proc: Process,
    ) -> "FileDescriptor | Err":
        """Open a file and return its file descriptor. open(2).

        If the file does not exist then it is created if the O_CREAT
        flag is set using the given `mode`.

        It is allowed to open() directories in O_RDONLY, such that one
        can call fsync(fd) on its file descriptor to ensure its
        (meta)data is written to disk.

        Args:
            pathname: Required to be an absolute path, for our
                implementation.
            proc: The process that called open(). Usually this argument
                is not passed to open() as the kernel knows which
                process called open(). We need it to determine the value
                for the file descriptor and store it in the process' open
                file table.

        Returns:
            On success returns the new file descriptor, else a
            non-positive integer is returned to indicate the error. See
            the ERRORS section in open(2).

        """
        if stat.S_ISDIR(mode) and flags & os.O_CREAT:
            return -errno.EINVAL
        if stat.S_ISREG(mode) and pathname.endswith("/"):
            # Our filesystem doesn't allow filenames ending with `/` as
            # to not confuse it with directories.
            return -errno.EINVAL

        sb, pathname = self._get_superblock(pathname)
        status, inode = Inode.lookup(pathname, sb)
        if status == 0 and flags & os.O_CREAT and flags & os.O_EXCL:
            return -errno.EEXIST
        elif status == -1:
            if flags & os.O_CREAT == 0:
                # No such file or directory.
                return -errno.ENOENT
            else:
                p_inode = inode
                # Create pathname as regular file, just as open(2) would
                # do.
                if (inode := sb.alloc_inode()) is None:
                    # Inode quota is reached.
                    return -errno.EDQUOT
                inode.create(p_inode=p_inode, mode=mode)
                # Point the parent directory inode to the newly created
                # inode so that we can lookup() it in the future. In the
                # Linux kernel, this part would likely manipulate the
                # dentry.
                fname = os.path.basename(pathname)
                p_inode.add_dir_entry(fname, inode)
        elif status == -2:
            # A directory component in pathname does not exist.
            return -errno.ENOENT
        elif status < 0:
            return status

        try:
            fd = proc.oft.index(None)
        except ValueError:
            # Maximum number of file descriptors is reached.
            return -errno.EMFILE

        if (
            stat.S_ISREG(mode)
            and flags & os.O_TRUNC
            and flags & (os.O_RDWR | os.O_WRONLY)
        ):
            # Truncate the file to length 0.
            inode.i_sb.dealloc_dblocks(inode.blocks)
            inode.blocks = []
            inode.i_size = 0

        # TODO: check flags for access mode. Do we even have permission
        # to open this file?
        ...

        f = File(
            inode=inode,
            flags=flags,
        )
        f.open()
        proc.oft[fd] = f

        return fd

    def close(self, fd: "FileDescriptor", proc: Process) -> "ResultInt":
        """Close a file descriptor. close(2).

        Returns:
            0: success.
            -EBADF: not a valid fd.

        """
        if fd < 0 or (file := proc.oft[fd]) is None:
            return -errno.EBADF
        else:
            proc.oft[fd] = None

        if hasattr(file, "flush"):
            file.flush()

        # Operations on the file might have changed the underlying
        # inode, e.g. by increasing the file size new data blocks would
        # have been allocated.
        inode = file.inode
        sb = file.inode.i_sb
        sb.write_inode(inode)
        return 0

    def write(self, fd: "FileDescriptor", buf: bytes, proc: Process) -> "Err | int":
        """Write bytes from buf to fd at file offset.

        Usually this method also takes a `count` parameter, but it is
        omitted here as to keep a similar signature with Python's file
        stream API.

        """
        if (file := proc.oft[fd]) is None:
            return -errno.EBADF  # Not a valid fd.
        else:
            return file.write(buf)

    def read(self, fd: "FileDescriptor", count: int, proc: Process) -> "bytearray | Err":
        """Read count bytes from the file at fd."""
        if (file := proc.oft[fd]) is None:
            return -errno.EBADF  # Not a valid fd.
        else:
            return file.read(count)

    def seek(self, fd: "FileDescriptor", offset: int, proc: Process) -> "Err | int":
        """Reposition file offset of file descriptor. lseek(2)."""
        if (file := proc.oft[fd]) is None:
            return -errno.EBADF  # Not a valid fd.
        else:
            return file.seek(offset)

    def mkdir(self, pathname: str, mode: int) -> "ResultInt":
        """Create a directory. mkdir(2).

        Normally, the pathname can be relative and is interpreted with
        respect to the current working directory of the process. In this
        implementation, however, only an absolute pathname is allowed
        (for simplicity).

        """
        sb, pathname = self._get_superblock(pathname)
        status, p_inode = Inode.lookup(pathname, sb)
        if status == 0:
            return -errno.EEXIST
        elif status == -2:
            # A directory component in pathname does not exist.
            return -errno.ENOENT
        elif status < -2:
            return status

        inode = sb.alloc_inode()
        if inode is None:
            # Inode quota is reached.
            return -errno.EDQUOT
        # Link to parent
        inode.p_ino = p_inode.i_ino
        inode.mkdir(mode=mode)
        # Link parent to new directory
        fname = os.path.basename(pathname)
        p_inode.add_dir_entry(fname, inode)
        return 0

    def _get_superblock(self, pathname: str) -> tuple[SuperBlock, str]:
        # Consider subdirectories first, e.g. having a mountpoint at
        # `/mnt` and `/` should first `/mnt` as it is otherwise never
        # considered.
        for mountpoint in sorted(self.sblocks, reverse=True):
            if pathname.startswith(mountpoint):
                sb = self.sblocks[mountpoint]
                if mountpoint != "/":
                    pathname = pathname.removeprefix(mountpoint) or "/"
                return sb, pathname

        raise ValueError("Pathname does not exist in managed superblocks.")
