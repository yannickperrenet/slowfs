import stat

import pytest

from linux.fs import INODE_SIZE
from linux.fs.super import SuperBlock
from linux.fs.inode import Inode, _DIR_LAYOUT_SIZE, _DIR_LAYOUT


def test_dir_layout():
    import struct
    fname = "Hello-world".encode("ascii")
    data = struct.pack(_DIR_LAYOUT, 10, len(fname), fname)
    assert len(data) == _DIR_LAYOUT_SIZE


def test_serialization(super: SuperBlock):
    inode = Inode(
        sb=super,
        ino=156,
        mode=14,
        size=256,
        num_f_in_dir=0,
        # Pick a random block from the data zone.
        blocks=[(1, super.dzone[1])],
        p_ino=super.root.i_ino,
    )
    assert len(bytes(inode)) == INODE_SIZE

    inode_dec = Inode.from_bytes(bytes(inode), sb=super)
    assert inode == inode_dec, "Same byte representation required"

    for vname, value in vars(inode).items():
        if vname == "i_sb":
            # We passed in the same super object
            continue

        assert getattr(inode_dec, vname) == value


def test_reg(super: SuperBlock):
    inode = Inode(sb=super, ino=2, p_ino=1)
    super.inodes[inode.i_ino] = inode

    assert inode.create() == 0, "Success"
    assert stat.S_ISREG(inode.i_mode)

    assert super.root.add_dir_entry("myfile", inode) == 0
    status, _ = Inode.lookup("/myfile", super)
    assert status == 0
    status, _ = Inode.lookup("/filemy", super)
    assert status == -1

    # Create file inside file.
    f_inode = Inode(sb=super, ino=3, p_ino=inode.i_ino)
    assert f_inode.create() == 0, "Success"
    with pytest.raises(ValueError):
        inode.add_dir_entry("myfile", inode)


def test_dir(super: SuperBlock):
    inode = Inode(sb=super, ino=2, p_ino=super.root.i_ino)
    super.inodes[inode.i_ino] = inode  # store in dentry-like map

    assert inode.mkdir() == 0, "Success"
    assert stat.S_ISDIR(inode.i_mode)

    assert super.root.add_dir_entry("subdir", inode) == 0
    status, _ = Inode.lookup("/subdir", super)
    assert status == 0
    status, _ = Inode.lookup("/dirsub", super)
    assert status == -1, "Subdirectory doesn't exist."

    # Create file inside directory.
    f_inode = Inode(sb=super, ino=3, p_ino=inode.i_ino)
    assert f_inode.create() == 0, "Success"
    assert inode.add_dir_entry("myfile", inode) == 0, "Add file to subdirectory"

    status, _ = Inode.lookup("/subdir/myfile", super)
    assert status == 0
    status, _ = Inode.lookup("/dirsub/myfile", super)
    assert status == -2, "Subdirectory doesn't exist"
    status, _ = Inode.lookup("/dirsub/filemy", super)
    assert status == -2, "Subdirectory doesn't exist"
    status, _ = Inode.lookup("/subdir/filemy", super)
    assert status == -1, "File doesn't exist, but subdirectory does."
