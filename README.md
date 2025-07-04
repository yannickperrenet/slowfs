# slowfs

A filesystem written in Python (with only the standard library) to learn about Linux filesystems.

To interact with the filesystem through "system calls" a block device and driver are implemented as
well as the concept of a process.

```python
# ... redacted ...
syscall_tbl = util.start_kernel(vfs=VFS)
proc = Process(syscall_tbl)
proc.mkdir(
    pathname="/mountpoint/mydir",
)
fd = proc.open(
    pathname="/mountpoint/mydir/file",
    flags=os.O_CREAT | os.O_RDWR,
    mode=0o644,
)
proc.write(fd, b"Hello world from a subdirectory")
proc.seek(fd, 0)
assert proc.read(fd, 11) == b"Hello world"
proc.close(fd)
```

The implementation tries to closely mimic the [Linux Virtual File System
(VFS)](https://docs.kernel.org/filesystems/vfs.html) and structures it similar to the [Linux
kernel](https://github.com/torvalds/linux/blob/master/fs/ext4/inode.c). Instead of defining a
`struct` of operations to tell the VFS how it can manipulate the object, e.g. `struct
inode_operations`, this implementation takes an object oriented approach to essentially namespace
the operations in a Python class.

```plain
linux
├── block
│   ├── device.py
│   └── driver.py
├── fs
│   ├── file.py
│   ├── inode.py
│   ├── super.py
│   └── vfs.py
└── sched.py
```

Since the code is written for learning purposes the resulting filesystem is slow, hence the name
*slowfs*, and severely limited:

-   Only supports regular files and directories (e.g. no symlinks).
-   Linux style file paths, i.e. using `/` as a separator. As for filenames: only ASCII and a
    maximum length of 27 characters.
-   No support for deleting files and directories.
-   No file permissions.
-   No indirect pointers in inode blocks, resulting in a maximum file size of ~242KB.
-   All inodes are cached in memory without any eviction policy, which wouldn't be feasible in
    production grade filesystems.

The biggest differences with filesystems in the Linux kernel are (besides the above):

-   No directory entry cache.

    Instead, whenever a file is looked up, we recursively search starting at the root of the
    filesystem without using caching. Since many of the methods in VFS expect a `dentry` argument
    (representing the cache), this implementation slightly deviates in terms of function signatures.

-   No page cache.

    This optimization is hard to mimic in Python and is not directly important to understand the
    inner working of a file system.

-   No pre-allocation strategy for blocks.


## Examples

There are two examples provided:

-   [high_level.py](examples/high_level.py) showing the high-level API to interact with the slowfs
    filesystem.

    ```sh
    uv run examples/high_level.py
    ```

-   [fuse_slowfs.py](examples/fuse_slowfs.py) serving slowfs through FUSE, allowing users to mount
    the fileystem on their system and interact with it using standard system calls, e.g. creating
    directories and writing to files.

    ```sh
    mkdir mnt/ && uv run examples/fuse_slowfs.py mnt/

    # Interact with the filesytem:
    mkdir mnt/mydir
    echo "Hello world" > mnt/dir/file
    cat mnt/dir/file
    ls -al mnt/dir

    # Interaction through Python:
    python3 -c 'with open("mnt/file", "w") as f: f.write("Hello world")'
    ```

### slowfs through FUSE

<img src="./assets/fuse-slowfs.svg" alt="Flowchart: Application interacting with slowfs through FUSE" width="350">

A FUSE filesystem consists of two parts:

-   Kernel space

    Here, a mapping is maintained between inode numbers and files/directories within the FUSE
    filesystem. This mapping is solely used for operations within the kernel. Note, these inodes are
    not represented by on-disk structures like in other native Linux filesystems (such as ext4).

-   User space

    Here, the FUSE server (slowfs) is responsible for storing and managing filesystem metadata and
    listening for requests coming from kernel space about this metadata. The server can store this
    information in any way it sees fit, e.g. in memory, in a database or (as slowfs does it) by
    implementing its own filesystem (which again goes through the VFS to access persistent storage).

In essence, FUSE inodes exist as identifiers managed by the kernel, while their attributes and
content are handled by a userspace program.

## Tests

```sh
# Tests
uv run pytest -v
# Type checking
uv run pyright src tests
# Get html coverage report
uv run coverage run -m pytest && uv run coverage html
```

## Acknowledgements

The idea behind the core of the filesystem was taken from the Persistence chapter from the excellent
free online book [Operating Systems: Three Easy Pieces](https://www.ostep.org/).
Most definitely worth a read (or quickly skim through my
[summary.md](notes/summary-ostep.md))! For other chapters they have some code on [their
GitHub](https://github.com/remzi-arpacidusseau/ostep-code).
