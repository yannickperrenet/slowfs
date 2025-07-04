"""Serve slowfs through FUSE.

Hacky implementation to be able to serve slowfs through FUSE. It was not
built for the purpose of integrating with FUSE but doing so gives users
a fimiliar interface to interact with. Note how fuse is a filesystem
that is part of the linux kernel and thus already takes care of inodes
and such, just like our filesystem.

Running and interacting with the filesystem in userspace:

```sh
mkdir mnt/
uv run examples/fuse_slowfs.py mnt/

# Show the filesystem type of the mountpoint.
stat -f -c %T <mountpoint>
# -> fuseblk
df <mountpoint>
# -> Filesystem        ...
# -> fuse_slowfs.py    ...

# Interact with the filesytem:
mkdir mnt/dir
echo "Hello world" > mnt/dir/file
cat mnt/dir/file
ls -al mnt/dir

# Don't forget to unmount when you're done.
sudo umount mnt/
# Or use:
fusermount -u mnt/
```

For other examples of FUSE w/ Python, see:

    https://gitlab.com/gunnarwolf/fuse_in_python_guide

    Run them like: `python3 dnsfs.py <mountpoint>`

"""

import errno
import os
import stat
import typing

import fuse

import util
from linux.block.device import Disk
from linux.fs.inode import Inode, _deserialize_dir_content
from linux.fs.vfs import VFS
from linux.sched import Process

if typing.TYPE_CHECKING:
    from linux.types import Err, ResultInt

fuse.fuse_python_api = (0, 2)
# NOTE: Use an absolute path so we can, if we want to, inspect the file
# after FUSE creates it.
SLOWFS_STORAGE_PATH = "/tmp/fuse_slowfs.raw"

# To debug this implementation use logs, e.g.:
# with open("/tmp/slowfs-logs", "w") as f: f.write("LOG: ...")

def create_slowfs_blockdev(pathname: str) -> Disk:
    """Create the slowfs filesystem in a file at pathname.

    Note, block devices are just files in Linux.

    Returns a block device object on top of the file at pathname.

    """
    if not os.path.exists(pathname):
        fname = os.path.basename(pathname)
        path = pathname.removesuffix(fname)
        os.makedirs(path, exist_ok=True)
        with open(pathname, "w") as _: ...  # create empty file
        disk = Disk(pathname)
        util.mkfs_slowfs(disk=disk)
    else:
        disk = Disk(pathname)

    return disk


# https://github.com/libfuse/python-fuse/blob/master/README.new_fusepy_api.rst
#
# >>> fuse.Fuse._attrs
# ['getattr', 'readlink', 'readdir', 'mknod', 'mkdir', 'unlink', 'rmdir',
# 'symlink', 'rename', 'link', 'chmod', 'chown', 'truncate', 'utime',
# 'open', 'read', 'write', 'release', 'statfs', 'fsync', 'create',
# 'opendir', 'releasedir', 'fsyncdir', 'flush', 'fgetattr', 'ftruncate',
# 'getxattr', 'listxattr', 'setxattr', 'removexattr', 'access', 'lock',
# 'utimens', 'bmap', 'fsinit', 'fsdestroy', 'ioctl', 'poll']

class SlowFS(fuse.Fuse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.syscall_tbl = util.start_kernel(vfs=VFS)
        self.proc = Process(self.syscall_tbl)
        self.disk = create_slowfs_blockdev(SLOWFS_STORAGE_PATH)

        # TODO: Get from sys.argv
        self.proc.mount(self.disk, "/")

    def getattr(self, path: str) -> "fuse.Stat | Err":
        supers = self.proc.sysfs()
        if not supers:
            return -errno.ENOENT
        sb = supers["/"]
        status, inode = Inode.lookup(path, sb=sb)
        if status != 0:
            if status < -2:
                return status
            else:
                return -errno.ENOENT

        st = fuse.Stat()
        st.st_mode = inode.i_mode
        st.st_size = inode.i_size
        # TODO: This nlink value is wrong, but without specifying a
        # value FUSE won't work.
        st.st_nlink = 1
        return st

    def mkdir(self, path: str, mode: int) -> "ResultInt":
        res = self.proc.mkdir(pathname=path, mode=mode)
        self._persist()
        return res

    def mknod(self, path: str, mode: int, dev) -> "ResultInt":
        # Use the open() call with O_CREAT flag to create a file.
        fd = self.proc.open(
            pathname=path,
            flags=os.O_CREAT | os.O_RDWR,
            mode=mode,
        )
        # Error.
        if fd < 0:
            return fd
        res = self.proc.close(fd)
        self._persist()
        return res

    def read(self, path: str, size: int, offset: int) -> "bytearray | Err":
        fd = self.proc.open(
            pathname=path,
            flags=os.O_RDONLY,
            mode=0o644,
        )
        # Error.
        if fd < 0:
            return fd

        err = self.proc.seek(fd=fd, offset=offset)
        if err < 0:
            return err
        ans = self.proc.read(fd=fd, count=size)
        self.proc.close(fd)
        return ans

    def write(self, path: str, buf: bytes, offset: int) -> "int | Err":
        fd = self.proc.open(
            pathname=path,
            flags=os.O_CREAT | os.O_RDWR,
            mode=0o644,
        )
        # Error.
        if fd < 0:
            return fd

        err = self.proc.seek(fd=fd, offset=offset)
        if err < 0:
            return err
        ans = self.proc.write(fd=fd, buf=buf)
        self.proc.close(fd)
        self._persist()
        return ans

    def readdir(self, path: str, offset: int):
        supers = self.proc.sysfs()
        if not supers:
            return -errno.ENOENT
        sb = supers["/"]
        status, inode = Inode.lookup(path, sb=sb)
        if status != 0:
            if status < -2:
                return status
            else:
                return -errno.ENOENT

        if not stat.S_ISDIR(inode.i_mode):
            return -errno.ENOTDIR

        for _, block in inode.blocks:
            for ino, name in _deserialize_dir_content(block):
                if ino == 0:
                    break

                yield fuse.Direntry(name.decode(encoding="ascii"))

    def _persist(self) -> None:
        """Persist filesystem changes to disk.

        FUSE doesn't implement it directly so we simply invoke it on
        every filesystem change.

        """
        supers = self.proc.sysfs()
        if not supers:
            return
        sb = supers["/"]
        sb.sync_fs()


def main():
    usage = "Slowfs: A slow filesystem." + fuse.Fuse.fusage
    server = SlowFS(
        version="%prog " + fuse.__version__,
        usage=usage,
        dash_s_do="setsingle"
    )

    server.parse(errex=1)
    server.main()


if __name__ == '__main__':
    main()
