from linux.fs.super import BitMap


def test_allocation():
    size = 1
    bm = BitMap(size=size)
    for i in range(5):
        assert bm.next_free() == i
        bm.alloc(i)

def test_allocation_large():
    size = 100
    bm = BitMap(size=size)
    for i in range(8*size):
        assert bm.next_free() == i
        bm.alloc(i)

def test_full():
    # Size is in bytes.
    size = 1
    bm = BitMap(size=size)
    # Allocate all the bits in the byte.
    for i in range(8*size):
        assert bm.next_free() == i
        bm.alloc(i)

    assert bm.next_free() == -1, "The BitMap should be full."

def test_free():
    size = 1
    bm = BitMap(size=size)

    for i in range(5):
        bm.alloc(i)
    bm.free(1)
    assert bm.next_free() == 1
    bm.free(0)
    assert bm.next_free() == 0

def test_iter():
    size = 1
    bm = BitMap(size=size)
    bm.alloc(2)
    bm.alloc(3)
    bm.alloc(5)
    allocated = [i for i in bm]
    assert allocated == [2, 3, 5]
