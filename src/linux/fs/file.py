import errno
import math
import os
import stat
import typing

from linux.block import BLOCK_SIZE
from linux.fs.inode import Inode

if typing.TYPE_CHECKING:
    from linux.types import Err, Success, ResultInt


# https://github.com/torvalds/linux/blob/fe78e02600f83d81e55f6fc352d82c4f264a2901/include/linux/fs.h#L1070
# https://docs.kernel.org/filesystems/api-summary.html#c.file
class File:
    """Open file object.

    Entry within the Open File Table (OTF) and accessed using its file
    descriptor.

    """
    def __init__(self, inode: Inode, offset: int = 0, flags: int = 0):
        # Cached inode.
        self.inode = inode
        # f_pos: file position (offset)
        self.offset = offset
        # File flags to hold info as to how the file was opened,
        # e.g. O_RDONLY. NOTE: Inode.mode has the filetype and
        # permissions.
        self.flags = flags
        # f_owner: file owner
        # f_path: path of the file
        # f_res: reference count

    def seek(self, offset: int) -> "int | Err":
        """Reposition file offset. lseek(2).

        Contrary to lseek(2), we do not allow the offset to be set
        beyond the end of the file. It is simpler not having to worry
        about gaps that are then created. Search for "hole" within the
        man page of lseek(2) for more information.

        Returns the resulting offset location in bytes or an error.

        """
        # Note, lseek(2) allows the file offset to be set beyond the end
        # of the file (but this does not change the size of the file).

        # This error is not actually returned by lseek(2), but we won't
        # support seeking on a directory.
        if stat.S_ISDIR(self.inode.i_mode):
            return -errno.EISDIR

        if offset > self.inode.i_size:
            return -errno.ENXIO
        self.offset = offset
        return self.offset

    def read(self, count: int) -> "bytearray | Err":
        """Read count bytes from the File at offset.

        From read(2) (emphasis mine):

            If the file offset is at or **past** the end of file, no
            bytes are read, and read() returns zero.

        Moreover, our implementation does not implement any form of
        buffering. Thus reads go directly through the block device. This
        means that if another File points to the same inode, then it can
        change the content of the file in between reads.

        """
        if stat.S_ISDIR(self.inode.i_mode):
            return -errno.EISDIR
        if self.flags & os.O_WRONLY:
            # File is not open for reading.
            return -errno.EBADF

        blocks = self.inode.blocks
        avail = self.inode.i_size - self.offset
        to_read = min(avail, count)
        buf = bytearray(to_read)
        ptr_buf = 0
        while to_read > 0:
            b, b_offset = divmod(self.offset, BLOCK_SIZE)
            _, block = blocks[b]
            size = min(BLOCK_SIZE - b_offset, to_read)
            buf[ptr_buf:ptr_buf+size] = block[b_offset:b_offset+size]
            self.offset += size
            to_read -= size
            ptr_buf += size

        return buf

    def write(self, buf: bytes) -> "int | Err":
        """Write buf to file at offset.

        Since we haven't implemented a page cache, writing will
        immediately write to the storage medium. Essentially doing a
        write(2) followed by an fsync(2).

        Returns the number of written bytes or an error code.

        Errors:
            ENOSPC: No room for the data.
            EBADF: Not a valid fd, or not open for writing.
            EISDIR: We don't allow writing to a directory.

        """
        # This error is not actually returned by write(2), but we won't
        # support it anyways.
        if stat.S_ISDIR(self.inode.i_mode):
            return -errno.EISDIR
        if not self.flags & (os.O_WRONLY | os.O_RDWR):
            # File is not open for writing.
            return -errno.EBADF

        if self.flags & os.O_APPEND:
            # Before each write(2), the file offset is positioned at the
            # end of the file, as if with lseek(2).
            self.offset = self.inode.i_size

        # Allocate new blocks if inode doesn't have enough space.
        sb = self.inode.i_sb
        avail = self.inode.i_size - self.offset
        n = len(buf)
        if n > avail:
            need = math.ceil((n - avail) / BLOCK_SIZE)
            err = self.inode.alloc_dblocks(need)
            if err != 0:
                # Fail immediately instead of partially writing buf.
                return err

        # Write bytes
        blocks = self.inode.blocks
        b, offset = divmod(self.offset, BLOCK_SIZE)
        ptr_buf = 0
        mem = memoryview(buf)
        for i in range(b, len(blocks)):
            _, block = blocks[i]

            to_write = min(BLOCK_SIZE - offset, n - ptr_buf)
            block.write(offset, mem[ptr_buf:ptr_buf+to_write])
            ptr_buf += to_write
            self.offset += to_write

            offset = 0
            if ptr_buf >= n:
                break

        self.inode.i_size = max(self.inode.i_size, self.offset)
        # TODO: note that this makes opening the same file multiple
        # times not possible. Because the inode can change whilst
        # another is reading it at the same time. However, with this
        # implementation those changes are propagated. The inode
        # would've to be read from the storage medium again. Thus
        # for now, a file can only be opened once.
        #
        # NOTE: The above is fixed since all inodes are currently
        # kept in memory. However, as the #inodes grows it could
        # become infeasible to do so and we would need a new solution.
        sb.write_inode(inode=self.inode)

        # Success returns the number of written bytes.
        return n

    def flush(self) -> "ResultInt":
        """Write content to disk."""
        # Empty, since self.write() already stores it to the
        # underlying Blocks. This function would change when a page
        # cache exists.
        return 0

    def open(self) -> "Success":
        # The open() method is a good place to initialize the
        # "private_data" member in the file structure if you want to
        # point to a device structure.
        # See: https://docs.kernel.org/filesystems/vfs.html#id2
        return 0
