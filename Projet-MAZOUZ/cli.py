
#!/usr/bin/env python3
import argparse, json, random, time
from bitpacking import PackerFactory

def measure(fn, *args, repeat=5, warmup=1):
    for _ in range(warmup):
        fn(*args)
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter_ns()
        fn(*args)
        t1 = time.perf_counter_ns()
        times.append(t1 - t0)
    return min(times)

def run_once(kind: str, n: int, max_val: int, signed: bool=False, zigzag: bool=False, seed: int=0):
    rnd = random.Random(seed)
    if signed:
        arr = [rnd.randint(-max_val, max_val) for _ in range(n)]
    else:
        arr = [rnd.randint(0, max_val) for _ in range(n)]
    packer = PackerFactory.create(kind, signed=signed, zigzag=zigzag)

    t_comp_ns = measure(packer.compress, arr, repeat=7, warmup=2)

    idxs = [rnd.randrange(n) for _ in range(min(1000, max(1, n)))]
    def do_gets():
        s = 0
        for i in idxs:
            s ^= packer.get(i)
        return s
    t_get_ns = measure(do_gets, repeat=7, warmup=2)

    out = [0]*n
    t_decomp_ns = measure(packer.decompress, out, repeat=5, warmup=1)

    ok = (out == arr)
    if kind.startswith("overflow"):
        total_bits = packer.n * packer.B_main + packer.m * packer.k_over
    else:
        total_bits = packer.n * packer.k
    comp_bytes = (total_bits + 7) // 8
    uncomp_bytes = 4 * n
    ratio = comp_bytes / uncomp_bytes if uncomp_bytes else 1.0

    return {
        "ok": ok,
        "n": n,
        "max_val": max_val,
        "signed": signed,
        "zigzag": zigzag,
        "kind": kind,
        "k": getattr(packer, "k", getattr(packer, "B_main", None)),
        "compressed_bytes": comp_bytes,
        "uncompressed_bytes": uncomp_bytes,
        "ratio": ratio,
        "t_compress_ns": t_comp_ns,
        "t_get_ns": t_get_ns,
        "t_decompress_ns": t_decomp_ns,
    }

def break_even_bandwidth_bits_per_s(result):
    C = result["t_compress_ns"] / 1e9
    D = result["t_decompress_ns"] / 1e9
    n = result["n"]
    if result["kind"].startswith("overflow"):
        Bc = (result["compressed_bytes"] * 8)
    else:
        Bc = result["k"] * n
    savings_bits = 32*n - Bc
    if savings_bits <= 0 or (C + D) <= 0:
        return 0.0
    return savings_bits / (C + D)

def total_time_seconds(result, latency_s: float, bitrate_bits_per_s: float):
    n = result["n"]
    T0 = latency_s + (32*n) / bitrate_bits_per_s
    C = result["t_compress_ns"]/1e9
    D = result["t_decompress_ns"]/1e9
    Bc = result["compressed_bytes"]*8
    T1 = latency_s + C + D + Bc / bitrate_bits_per_s
    return T0, T1

def main():
    ap = argparse.ArgumentParser(description="Bit packing demo + benchmarks")
    ap.add_argument("--kind", choices=["cross","nocross","overflow-cross","overflow-nocross"], default="cross")
    ap.add_argument("-n", type=int, default=1_000_000, help="array length")
    ap.add_argument("--max", dest="max_val", type=int, default=(1<<12)-1, help="max value magnitude")
    ap.add_argument("--signed", action="store_true")
    ap.add_argument("--zigzag", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--latency", type=float, default=0.050, help="one-way link latency in seconds")
    ap.add_argument("--bitrate", type=float, default=10e6, help="link bitrate in bits/s")
    args = ap.parse_args()

    res = run_once(args.kind, args.n, args.max_val, signed=args.signed, zigzag=args.zigzag, seed=args.seed)
    print(json.dumps(res, indent=2))

    R_be = break_even_bandwidth_bits_per_s(res)
    print(f"\nBreak-even bitrate R* (bits/s) where compression starts to help: {R_be:,.0f}")

    T0, T1 = total_time_seconds(res, args.latency, args.bitrate)
    print(f"Baseline (no compression) time @ latency={args.latency}s, bitrate={args.bitrate} bps: {T0:.6f} s")
    print(f"Compressed time                            @ latency={args.latency}s, bitrate={args.bitrate} bps: {T1:.6f} s")
    if T1 < T0:
        print("=> Compression is beneficial under these network parameters.")
    else:
        print("=> Compression is NOT beneficial under these network parameters.")

if __name__ == "__main__":
    main()
