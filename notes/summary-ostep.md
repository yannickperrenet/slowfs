# File system

[I/O Devices](https://pages.cs.wisc.edu/~remzi/OSTEP/file-devices.pdf)

**Devices** such as disks have a set of registers for the **CPU** to read and write to. Messages
travel over an I/O bus, such as **PCI**, from the CPU to the **device registers**. In general these
registers allow the CPU to: check the status of the device(e.g. busy, done), write a command for the
device to execute, read/write data from/to the device.

To ensure the CPU doesn't constantly have to poll the device for its status (e.g. is it done getting
me the data block I asked for?), since that would keep the CPU busy, the OS makes use of
**interrupts** to wake up the requesting process when the task is done.

Furthermore, the CPU often has to write data from memory to a particular device (e.g. to write a
chunk of data). Whilst the CPU is copying this data, it can't run any other tasks. To alleviate the
CPU the **Direct Memory Access (DMA)** engine was invented to orchestrate transfers between memory and
devices. The CPU tells the DMA to copy specific data from memory to a particular device and itself
can run other tasks in the meantime (until the interrupt happens to tell the CPU that this data has
been copied).

Since there are many devices and we want the kernel to be as generic as possible, **device drivers**
abstract away the exact instructions that are needed to interact with the device and instead offer a
generic API. For example, the CPU no longer needs to know the specific register of a device and can
instead just issue a `read`.


[Hard Disk Drives - HDD](https://pages.cs.wisc.edu/~remzi/OSTEP/file-disks.pdf)

1 sector = 512-byte block; smallest unit of atomic write
Filesystems read/write 4KB at a time
1 track = multiple sectors (in a circle on the disk surface)

seek = position disk head over correct track that holds the sector(s) we want to read. Takes ~2ms
HDD spins at specific RPM which gives the time of a rotational delay, e.g. 6ms for 10.000 RPM

When the head is positioned at a specific track it has to wait until the specific sector it wants is
positioned under the head incurring a rotational delay.

Disk drives also hold a small cache, ~16MB, to hold data read from or written to the disk. For
example, the disk might cache a whole track to service future reads faster. Moreover:

>   On writes, the drive has a choice: should it acknowledge the write has completed when it has put
>   the data in its memory, or after the write has actually been written to disk? The former is
>   called write back caching (or sometimes immediate reporting), and the latter write through.
>   Write back caching sometimes makes the drive appear "faster", but can be dangerous; if the
>   file system or applications require that data be written to disk in a certain order for
>   correctness, write-back caching can lead to problems

Lastly, the OS and disk implement a **disk scheduler** that examines the I/O requests and decides
the order of those requests to achieve the best performance. There are different algorithms that
have different approaches to this scheduling, some important characteristics are (in no particular
order): (1) merge I/O requests of sequential sectors, (2) reduce seek time by using the current head
position. Examples of such algorithms are **SCAN**, F-SCAN and C-SCAN.


[Files and Directories](https://pages.cs.wisc.edu/~remzi/OSTEP/file-intro.pdf)

File descriptors are managed by the OS on a per-process basis, i.e. the `proc` struct contains a
list of its open files. These file descriptors can then be used to `read()` and `write()`.

Track system calls of a program using `strace <command>`.

```C
struct proc {
    // ...
    // file descriptor is an integer into this array -> open file description
    struct file *ofile[NOFILE]; // Open files
    // ...
};

// See: https://docs.kernel.org/filesystems/vfs.html
struct file { // open file description inside the OFT
    int ref;  // reference counter
    char readable;
    char writable;
    struct inode *ip;  // the underlying file it points to
    uint off; // current offset in the file
    // ...
}

// Open File Table (OFT) keeps track of all open `file`s in the system
// as an array, tracking the offset and `inode`.
```

Each time you `open()` a file it will get its own file descriptor and a new entry in the OFT such
that each can have its own offset in the file. Moreover, if you `fork()` then the child file
descriptors point to the same entry in the OFT and thus modifies the offset of the `file` of the
parent. See also `man dup` and `man open.2`.

Note, you need to `fsync()` the file as well as directory it is created in (if newly created).


[FS Implementation](https://pages.cs.wisc.edu/~remzi/OSTEP/file-implementation.pdf)

Divide disk into blocks of 4KB.
