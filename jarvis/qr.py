"""A QR code of a short address (byte mode, error correction M, versions 1 to 6), without anything downloaded."""
from __future__ import annotations

# version: (data codewords, error correction codewords per block, blocks)   (level M)
_SIZE = {1: (16, 10, 1), 2: (28, 16, 1), 3: (44, 26, 1), 4: (64, 18, 2), 5: (86, 24, 2), 6: (108, 16, 4)}
_ALIGN = {1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30), 6: (6, 34)}

_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i], _LOG[_x] = _x, _i
    _x = (_x << 1) ^ (0x11D if _x & 0x80 else 0)
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if not a or not b else _EXP[_LOG[a] + _LOG[b]]


def _remainder(data: list[int], n: int) -> list[int]:
    gen = [1]
    for i in range(n):
        gen = _times(gen, _EXP[i])
    out = [0] * n
    for d in data:
        f = d ^ out[0]
        out = out[1:] + [0]
        for j in range(n):
            out[j] ^= _mul(gen[j + 1], f)
    return out


def _times(gen: list[int], root: int) -> list[int]:
    """(polynomial, highest power first) times (x - root)"""
    out = gen + [0]
    for j, g in enumerate(gen):
        out[j + 1] ^= _mul(g, root)
    return out


def _codewords(text: bytes) -> tuple[int, list[int]]:
    for v, (k, ec, blocks) in _SIZE.items():
        if len(text) + 2 <= k:
            break
    else:
        raise ValueError("Too long for a QR code.")
    bits = "0100" + f"{len(text):08b}" + "".join(f"{b:08b}" for b in text)
    bits += "0" * min(4, k * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    data += [0xEC if i % 2 == 0 else 0x11 for i in range(k - len(data))]
    short, long_n = k // blocks, k % blocks
    parts, at = [], 0
    for b in range(blocks):
        n = short + (1 if b >= blocks - long_n else 0)
        parts.append(data[at:at + n])
        at += n
    ecc = [_remainder(p, ec) for p in parts]
    out = [p[i] for i in range(short + 1) for p in parts if i < len(p)]
    out += [e[i] for i in range(ec) for e in ecc]
    return v, out


def _bch(value: int, poly: int, bits: int) -> int:
    v = value << bits
    for i in range(v.bit_length() - 1, bits - 1, -1):
        if v >> i & 1:
            v ^= poly << (i - bits)
    return value << bits | v


def _mask(m: int, r: int, c: int) -> bool:
    return [(r + c) % 2 == 0, r % 2 == 0, c % 3 == 0, (r + c) % 3 == 0, (r // 2 + c // 3) % 2 == 0, r * c % 2 + r * c % 3 == 0, (r * c % 2 + r * c % 3) % 2 == 0, ((r + c) % 2 + r * c % 3) % 2 == 0][m]


def _penalty(q: list[list[int]]) -> int:
    n, p = len(q), 0
    for lines in (q, [list(x) for x in zip(*q)]):
        for line in lines:
            run = 1
            for i in range(1, n + 1):
                if i < n and line[i] == line[i - 1]:
                    run += 1
                else:
                    p += run - 2 if run >= 5 else 0
                    run = 1
            s = "".join(map(str, line))
            for w in ("10111010000", "00001011101"):
                i = s.find(w)
                while i >= 0:
                    p += 40
                    i = s.find(w, i + 1)
    for r in range(n - 1):
        for c in range(n - 1):
            p += 3 if q[r][c] == q[r + 1][c] == q[r][c + 1] == q[r + 1][c + 1] else 0
    dark = sum(map(sum, q)) * 100 / (n * n)
    return p + int(abs(dark - 50) / 5) * 10


def matrix(text: str) -> list[list[int]]:
    """Rows of 0 and 1 (without the white edge)."""
    v, words = _codewords(text.encode("utf-8"))
    n = 17 + 4 * v
    q: list[list[int | None]] = [[None] * n for _ in range(n)]

    def finder(r: int, c: int) -> None:
        for i in range(-1, 8):
            for j in range(-1, 8):
                if 0 <= r + i < n and 0 <= c + j < n:
                    q[r + i][c + j] = int(0 <= i <= 6 and 0 <= j <= 6 and (i in (0, 6) or j in (0, 6) or 2 <= i <= 4 and 2 <= j <= 4))
    finder(0, 0), finder(0, n - 7), finder(n - 7, 0)
    for a in _ALIGN[v]:
        for b in _ALIGN[v]:
            if q[a][b] is None:
                for i in range(-2, 3):
                    for j in range(-2, 3):
                        q[a + i][b + j] = int(max(abs(i), abs(j)) != 1)
    for i in range(8, n - 8):
        q[6][i] = q[i][6] = int(i % 2 == 0)
    spots = [(8, i) for i in (0, 1, 2, 3, 4, 5, 7, 8)] + [(i, 8) for i in (7, 5, 4, 3, 2, 1, 0)], [(n - 1 - i, 8) for i in range(7)] + [(8, n - 8 + i) for i in range(8)]
    for s in spots:
        for r, c in s:
            q[r][c] = 0
    q[n - 8][8] = 1
    free = [[x is None for x in row] for row in q]
    bits = "".join(f"{w:08b}" for w in words) + "0" * 7
    k, up, c = 0, True, n - 1
    while c > 0:
        c -= c == 6
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for cc in (c, c - 1):
                if free[r][cc]:
                    q[r][cc] = int(bits[k])
                    k += 1
        up, c = not up, c - 2
    best: tuple[int, list[list[int]]] | None = None
    for m in range(8):
        t = [[int(x or 0) ^ int(free[r][cc] and _mask(m, r, cc)) for cc, x in enumerate(row)] for r, row in enumerate(q)]
        fmt = f"{_bch(0b00 << 3 | m, 0b10100110111, 10) ^ 0b101010000010010:015b}"
        for s in spots:
            for (r, cc), b in zip(s, fmt):
                t[r][cc] = int(b)
        t[n - 8][8] = 1
        p = _penalty(t)
        if best is None or p < best[0]:
            best = (p, t)
    assert best
    return best[1]


def svg(text: str) -> str:
    """Black on white with the white edge it needs (also in the dark theme)."""
    q = matrix(text)
    n = len(q) + 8
    path = "".join(f"M{c + 4} {r + 4}h1v1h-1z" for r, row in enumerate(q) for c, x in enumerate(row) if x)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges" role="img" aria-label="QR code"><rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>'
