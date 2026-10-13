"""Dependency-free QR codes for Agent Hub phone links (byte mode, EC M, v1–10)."""

ECC = (0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
BLOCKS = (0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)


def _bit(number, index):
    return bool((number >> index) & 1)


def _multiply(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _raw_codewords(version):
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
    if version >= 7:
        result -= 36
    return result // 8


def _divisor(degree):
    result = [0] * degree
    result[-1] = 1
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _multiply(root, 2)
    return result


def _remainder(data, divisor):
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result[0]
        result = result[1:] + [0]
        for j, value in enumerate(divisor):
            result[j] ^= _multiply(value, factor)
    return result


def _codewords(data, version):
    capacity = _raw_codewords(version) - ECC[version] * BLOCKS[version]
    count_bits = 8 if version < 10 else 16
    bits = []

    def append(value, length):
        bits.extend((value >> i) & 1 for i in range(length - 1, -1, -1))

    append(4, 4)
    append(len(data), count_bits)
    for byte in data:
        append(byte, 8)
    append(0, min(4, capacity * 8 - len(bits)))
    bits.extend([0] * (-len(bits) % 8))
    payload = [sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, len(bits), 8)]
    while len(payload) < capacity:
        payload.append(0xEC if len(payload) % 2 == (len(bits) // 8) % 2 else 0x11)
    short_count = BLOCKS[version] - _raw_codewords(version) % BLOCKS[version]
    short_data = _raw_codewords(version) // BLOCKS[version] - ECC[version]
    divisor = _divisor(ECC[version])
    blocks = []
    offset = 0
    for index in range(BLOCKS[version]):
        length = short_data + (index >= short_count)
        part = payload[offset:offset + length]
        offset += length
        blocks.append((part, _remainder(part, divisor)))
    result = []
    for j in range(short_data + 1):
        result.extend(part[j] for part, _ in blocks if j < len(part))
    for j in range(ECC[version]):
        result.extend(ecc[j] for _, ecc in blocks)
    return result


def _format(cells, fixed, mask):
    size = len(cells)

    def set_cell(x, y, dark):
        cells[y][x] = bool(dark)
        fixed[y][x] = True

    rem = mask  # EC level M has format bits 00.
    for _ in range(10):
        rem = (rem << 1) ^ (((rem >> 9) & 1) * 0x537)
    value = ((mask << 10) | rem) ^ 0x5412
    for i in range(6):
        set_cell(8, i, _bit(value, i))
    set_cell(8, 7, _bit(value, 6))
    set_cell(8, 8, _bit(value, 7))
    set_cell(7, 8, _bit(value, 8))
    for i in range(9, 15):
        set_cell(14 - i, 8, _bit(value, i))
    for i in range(8):
        set_cell(size - 1 - i, 8, _bit(value, i))
    for i in range(8, 15):
        set_cell(8, size - 15 + i, _bit(value, i))
    set_cell(8, size - 8, True)


def _base(version):
    size = version * 4 + 17
    cells = [[False] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def set_cell(x, y, dark):
        if 0 <= x < size and 0 <= y < size:
            cells[y][x] = bool(dark)
            fixed[y][x] = True

    for i in range(size):
        set_cell(6, i, i % 2 == 0)
        set_cell(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                distance = max(abs(dx), abs(dy))
                set_cell(cx + dx, cy + dy, distance not in (2, 4))
    if version >= 2:
        count = version // 7 + 2
        step = ((version * 4 + count * 2 + 1) // (count * 2 - 2)) * 2
        positions = [6] + [size - 7 - i * step for i in range(count - 2, -1, -1)]
        for x in positions:
            for y in positions:
                if (x, y) in ((6, 6), (6, size - 7), (size - 7, 6)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        set_cell(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)
    _format(cells, fixed, 0)
    if version >= 7:
        rem = version
        for _ in range(12):
            rem = (rem << 1) ^ (((rem >> 11) & 1) * 0x1F25)
        value = (version << 12) | rem
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            set_cell(a, b, _bit(value, i))
            set_cell(b, a, _bit(value, i))
    return cells, fixed


def _place(cells, fixed, codewords):
    size = len(cells)
    index = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
            for side in range(2):
                x = right - side
                if not fixed[y][x]:
                    cells[y][x] = index < len(codewords) * 8 and _bit(codewords[index >> 3], 7 - (index & 7))
                    index += 1
        right -= 2


def _mask_at(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (y // 2 + x // 3) % 2 == 0
    if mask == 5:
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:
        return (x * y % 2 + x * y % 3) % 2 == 0
    return ((x + y) % 2 + x * y % 3) % 2 == 0


def _penalty(cells):
    size = len(cells)
    score = 0
    for get in (lambda a, b: cells[a][b], lambda a, b: cells[b][a]):
        for outer in range(size):
            last, length = False, 0
            for inner in range(size):
                value = get(outer, inner)
                if inner == 0 or value != last:
                    if length >= 5:
                        score += 3 + length - 5
                    last, length = value, 1
                else:
                    length += 1
            if length >= 5:
                score += 3 + length - 5
        for outer in range(size):
            for inner in range(size - 10):
                word = ''.join('1' if get(outer, inner + i) else '0' for i in range(11))
                if word in ('10111010000', '00001011101'):
                    score += 40
    dark = 0
    for y in range(size):
        for x in range(size):
            dark += cells[y][x]
            if x and y and cells[y][x] == cells[y - 1][x] == cells[y][x - 1] == cells[y - 1][x - 1]:
                score += 3
    score += abs(dark * 20 - size * size * 10) // (size * size) * 10
    return score


def encode(text):
    """Return a square list of bools; raise ValueError if the text needs QR v11+."""
    if not isinstance(text, str):
        raise TypeError('QR input must be a string')
    data = text.encode('utf-8')
    for version in range(1, 11):
        capacity = _raw_codewords(version) - ECC[version] * BLOCKS[version]
        if len(data) < (256 if version < 10 else 65536) and 4 + (8 if version < 10 else 16) + len(data) * 8 <= capacity * 8:
            break
    else:
        raise ValueError('Address is too long for a QR code')
    cells, fixed = _base(version)
    _place(cells, fixed, _codewords(data, version))
    best, best_score = None, float('inf')
    for mask in range(8):
        candidate = [[cells[y][x] != (not fixed[y][x] and _mask_at(mask, x, y)) for x in range(len(cells))] for y in range(len(cells))]
        _format(candidate, [row.copy() for row in fixed], mask)
        score = _penalty(candidate)
        if score < best_score:
            best, best_score = candidate, score
    return best


def terminal_qr(text):
    """Return a QR with a four-module white border for terminals with ANSI color."""
    cells = encode(text)
    width = len(cells) + 8
    lines = []
    for row in [[False] * width] * 4 + [[False] * 4 + item + [False] * 4 for item in cells] + [[False] * width] * 4:
        current = None
        pieces = []
        for dark in row:
            if dark != current:
                pieces.append('\x1b[40m' if dark else '\x1b[47m')
                current = dark
            pieces.append('  ')
        pieces.append('\x1b[0m')
        lines.append(''.join(pieces))
    return '\n'.join(lines)
