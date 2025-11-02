
import random
from bitpacking import PackerFactory

def roundtrip(kind, arr, signed=False, zigzag=False):
    packer = PackerFactory.create(kind, signed=signed, zigzag=zigzag)
    packer.compress(arr)
    out = [0]*len(arr)
    packer.decompress(out)
    assert out == arr, f"roundtrip failed for {kind}"

def test_cross_basic():
    arr = [1,2,3,4095,4,5,255]
    roundtrip("cross", arr)

def test_nocross_basic():
    arr = [5]*1000
    roundtrip("nocross", arr)

def test_overflow_example():
    arr = [1,2,3,1024,4,5,2048]
    roundtrip("overflow-cross", arr)

def test_signed_zigzag():
    arr = [0, -1, 1, -2, 2, 1024, -1025]
    roundtrip("cross", arr, signed=False, zigzag=True)

def test_signed_twos_complement():
    rng = random.Random(0)
    arr = [rng.randint(-5000,5000) for _ in range(10000)]
    roundtrip("nocross", arr, signed=True, zigzag=False)
