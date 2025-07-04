import resource
import typing

if typing.TYPE_CHECKING:
    from linux.block.device import Disk
    from linux.fs.file import File
    from linux.fs.super import SuperBlock
    from linux.types import Err, FileDescriptor, ResultInt


class Process:
    """A Linux process.

    Exists in our implementation solely as a proxy to the VFS methods as
    otherwise we do not know which process invoked a system call. Which
    is sometimes needed to operate on the OFT that is stored within a
    process.

    """
    def __init__(self, syscalls: dict[str, typing.Callable]) -> None:
        # In the Linux kernel stdin, stdout and stderr would be assigned
        # the file descriptors 0, 1 and 2 respectively. These are
        # special files though (see `/dev/stdout`) and are not supported
        # by our file system.
        self.oft: "list[File | None]" = []
        for _ in range(resource.RLIMIT_NOFILE):
            self.oft.append(None)
        # NOTE: Ideally we use the more performant way:
        # self.oft: list[File | None] = resource.RLIMIT_NOFILE * [None]
        # However, lists in Python are invariant. Because File | None
        # is not a subtype of None (and vice versa), we can't do the
        # assignment. Otherwise, one would be able to do
        # l: list[None] = 10 * [None]
        # l[0] = 1
        # Thus when creating resource.RLIMIT_NOFILE * [None] Python
        # creates a list[None] (of which None | int thus isn't seen as
        # a subtype).
        # We are okay with this small performance penalty as the
        # RLIMIT_NOFILE tends to be very small.
        assert resource.RLIMIT_NOFILE < 100, "Performance degradation."

        # We can mimic security by only passing a subset of syscalls to
        # the process.
        self.syscalls = syscalls

    # --------
    # System calls
    # --------
    #
    # The kernel knows which process invoked a system call, but we do
    # not. So let's use Python's namespacing and define system calls
    # directly on a Process.

    def open(self, pathname: str, flags: int, mode: int) -> "FileDescriptor | Err":
        """open(2)."""
        return self.syscalls["open"](pathname=pathname, flags=flags, mode=mode, proc=self)

    def close(self, fd: "FileDescriptor") -> "ResultInt":
        """close(2)."""
        return self.syscalls["close"](fd=fd, proc=self)

    def write(self, fd: "FileDescriptor", buf: bytes) -> "int | Err":
        """write(2)."""
        return self.syscalls["write"](fd=fd, buf=buf, proc=self)

    def read(self, fd: "FileDescriptor", count: int) -> "bytearray | Err":
        """read(2)."""
        return self.syscalls["read"](fd=fd, count=count, proc=self)

    def seek(self, fd: "FileDescriptor", offset: int) -> "Err | int":
        """lseek(2)."""
        return self.syscalls["seek"](fd=fd, offset=offset, proc=self)

    def mkdir(self, pathname: str, mode: int = 0o744) -> "ResultInt":
        """mkdir(2)."""
        return self.syscalls["mkdir"](pathname=pathname, mode=mode)

    def mount(self, source: "Disk", target: str) -> int:
        """mount(2)."""
        return self.syscalls["mount"](blockdev=source, mountpoint=target)

    def umount(self, mountpoint: str) -> int:
        """umount(2)."""
        return self.syscalls["umount"](mountpoint=mountpoint)

    def sysfs(self) -> "dict[str, SuperBlock]":
        """sysfs(2)."""
        return self.syscalls["sysfs"]()
