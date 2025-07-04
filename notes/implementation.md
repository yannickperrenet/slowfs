# Resources to actually write a filesystem driver

[O'Reilly Linux Device Drivers](https://lwn.net/Kernel/LDD3/)

[example 1](https://www.uninformativ.de/blog/postings/2017-09-09/0/POSTING-en.html)
[MINIX](https://en.wikipedia.org/wiki/MINIX_file_system)

[loop device](https://askubuntu.com/questions/85977/how-do-i-create-a-file-and-mount-it-as-a-filesystem)

-   Using `mount -o loop=filename` the `filename` file will be treated as a block device.

[Tutorial simplefs](https://accelazh.github.io/linux/Writing-a-Kernel-Filesystem)
[Simplefs](https://github.com/psankar/simplefs/tree/master)
[API by kernel](https://docs.kernel.org/filesystems/vfs.html#overview-of-the-linux-virtual-file-system)

-   `struct inode_operations` shows you need to adhere to a certain structure
-   The tutorial shows that the kernel module registers to VFS and implements its hooks.

[ext2](https://tldp.org/LDP/tlk/fs/filesystem.html)

[Linux kernel](https://linux-kernel-labs.github.io/refs/heads/master/lectures/fs.html#inode-operations)

-   "The next set of operations that VFS calls when interacting with filesystem device drivers are
    the "inode operations"."
-   Thus I think I would have to write a kernel module that allows VFS to call these functions on my
    filesystem.
-   [Lab of creating a FS](https://linux-kernel-labs.github.io/refs/heads/master/labs/filesystems_part1.html#myfs)

(Possibly write the kernel module in Rust, but I guess its easier to just do in C.)
