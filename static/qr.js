/* Small, dependency-free QR encoder: byte mode, error correction M, versions 1–10. */
(() => {
  'use strict';
  const ECC = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  const BLOCKS = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
  const bit = (n, i) => ((n >>> i) & 1) !== 0;
  const mul = (x, y) => {
    let z = 0;
    for (let i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11d);
      z ^= ((y >>> i) & 1) * x;
    }
    return z;
  };
  function rawCodewords(version) {
    let n = (16 * version + 128) * version + 64;
    if (version >= 2) {
      const align = Math.floor(version / 7) + 2;
      n -= (25 * align - 10) * align - 55;
    }
    if (version >= 7) n -= 36;
    return Math.floor(n / 8);
  }
  function divisor(degree) {
    const d = new Uint8Array(degree);
    d[degree - 1] = 1;
    let root = 1;
    for (let i = 0; i < degree; i++) {
      for (let j = 0; j < degree; j++) {
        d[j] = mul(d[j], root);
        if (j + 1 < degree) d[j] ^= d[j + 1];
      }
      root = mul(root, 2);
    }
    return d;
  }
  function remainder(data, d) {
    const r = new Uint8Array(d.length);
    for (const byte of data) {
      const factor = byte ^ r[0];
      r.copyWithin(0, 1);
      r[r.length - 1] = 0;
      for (let i = 0; i < d.length; i++) r[i] ^= mul(d[i], factor);
    }
    return r;
  }
  function encodeData(bytes, version) {
    const countBits = version < 10 ? 8 : 16;
    const capacity = rawCodewords(version) - ECC[version] * BLOCKS[version];
    const bits = [];
    const append = (value, length) => { for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
    append(4, 4);
    append(bytes.length, countBits);
    for (const byte of bytes) append(byte, 8);
    append(0, Math.min(4, capacity * 8 - bits.length));
    while (bits.length % 8) bits.push(0);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(''), 2));
    for (let pad = 0; data.length < capacity; pad++) data.push(pad % 2 ? 0x11 : 0xec);
    const blocks = [];
    const shortCount = BLOCKS[version] - rawCodewords(version) % BLOCKS[version];
    const shortData = Math.floor(rawCodewords(version) / BLOCKS[version]) - ECC[version];
    const poly = divisor(ECC[version]);
    let offset = 0;
    for (let i = 0; i < BLOCKS[version]; i++) {
      const length = shortData + (i >= shortCount ? 1 : 0);
      const part = data.slice(offset, offset + length);
      offset += length;
      blocks.push({ data: part, ecc: [...remainder(part, poly)] });
    }
    const result = [];
    for (let j = 0; j <= shortData; j++) for (const block of blocks) if (j < block.data.length) result.push(block.data[j]);
    for (let j = 0; j < ECC[version]; j++) for (const block of blocks) result.push(block.ecc[j]);
    return result;
  }
  function makeBase(version) {
    const size = version * 4 + 17;
    const cells = Array.from({ length: size }, () => Array(size).fill(false));
    const fixed = Array.from({ length: size }, () => Array(size).fill(false));
    const set = (x, y, dark) => {
      if (x >= 0 && y >= 0 && x < size && y < size) { cells[y][x] = !!dark; fixed[y][x] = true; }
    };
    for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const distance = Math.max(Math.abs(dx), Math.abs(dy));
        set(cx + dx, cy + dy, distance !== 2 && distance !== 4);
      }
    }
    if (version >= 2) {
      const count = Math.floor(version / 7) + 2;
      const step = Math.floor((version * 4 + count * 2 + 1) / (count * 2 - 2)) * 2;
      const positions = [6];
      for (let i = count - 2; i >= 0; i--) positions.push(size - 7 - i * step);
      for (const x of positions) for (const y of positions) {
        if ((x === 6 && y === 6) || (x === 6 && y === size - 7) || (x === size - 7 && y === 6)) continue;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    }
    format({ size, set }, 0);
    if (version >= 7) {
      let rem = version;
      for (let i = 0; i < 12; i++) rem = (rem << 1) ^ (((rem >>> 11) & 1) * 0x1f25);
      const value = (version << 12) | rem;
      for (let i = 0; i < 18; i++) {
        const a = size - 11 + i % 3, b = Math.floor(i / 3);
        set(a, b, bit(value, i)); set(b, a, bit(value, i));
      }
    }
    return { size, cells, fixed, set };
  }
  function placeData(base, codewords) {
    const { size, cells, fixed } = base;
    let index = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) {
        const y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
        for (let side = 0; side < 2; side++) {
          const x = right - side;
          if (!fixed[y][x]) {
            cells[y][x] = index < codewords.length * 8 && bit(codewords[index >>> 3], 7 - (index & 7));
            index++;
          }
        }
      }
    }
  }
  function maskAt(mask, x, y) {
    switch (mask) {
      case 0: return (x + y) % 2 === 0;
      case 1: return y % 2 === 0;
      case 2: return x % 3 === 0;
      case 3: return (x + y) % 3 === 0;
      case 4: return (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0;
      case 5: return x * y % 2 + x * y % 3 === 0;
      case 6: return (x * y % 2 + x * y % 3) % 2 === 0;
      default: return ((x + y) % 2 + x * y % 3) % 2 === 0;
    }
  }
  function format(base, mask) {
    const { size, set } = base;
    let rem = mask; // M's format bits are 00.
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ (((rem >>> 9) & 1) * 0x537);
    const value = ((mask << 10) | rem) ^ 0x5412;
    for (let i = 0; i <= 5; i++) set(8, i, bit(value, i));
    set(8, 7, bit(value, 6)); set(8, 8, bit(value, 7)); set(7, 8, bit(value, 8));
    for (let i = 9; i < 15; i++) set(14 - i, 8, bit(value, i));
    for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(value, i));
    for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(value, i));
    set(8, size - 8, true);
  }
  function penalty(c) {
    const n = c.length;
    let score = 0, dark = 0;
    const run = (get) => {
      for (let outer = 0; outer < n; outer++) {
        let last = false, length = 0;
        for (let inner = 0; inner < n; inner++) {
          const value = get(outer, inner);
          if (inner === 0 || value !== last) { if (length >= 5) score += 3 + length - 5; length = 1; last = value; }
          else length++;
        }
        if (length >= 5) score += 3 + length - 5;
      }
    };
    run((y, x) => c[y][x]); run((x, y) => c[y][x]);
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      dark += c[y][x] ? 1 : 0;
      if (x && y && c[y][x] === c[y - 1][x] && c[y][x] === c[y][x - 1] && c[y][x] === c[y - 1][x - 1]) score += 3;
    }
    for (const get of [(a, b) => c[a][b], (a, b) => c[b][a]]) {
      for (let a = 0; a < n; a++) for (let b = 0; b + 10 < n; b++) {
        const word = Array.from({ length: 11 }, (_, i) => get(a, b + i) ? '1' : '0').join('');
        if (word === '10111010000' || word === '00001011101') score += 40;
      }
    }
    score += Math.floor(Math.abs(dark * 20 - n * n * 10) / (n * n)) * 10;
    return score;
  }
  function encode(text) {
    if (typeof text !== 'string') throw new TypeError('QR input must be a string');
    const bytes = new TextEncoder().encode(text);
    let version = 1;
    while (version <= 10) {
      const capacity = rawCodewords(version) - ECC[version] * BLOCKS[version];
      if (bytes.length < (version < 10 ? 256 : 65536) && 4 + (version < 10 ? 8 : 16) + bytes.length * 8 <= capacity * 8) break;
      version++;
    }
    if (version > 10) throw new RangeError('Address is too long for a QR code');
    const base = makeBase(version);
    placeData(base, encodeData(bytes, version));
    let best = null, bestScore = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const cells = base.cells.map((row, y) => row.map((value, x) => value !== (!base.fixed[y][x] && maskAt(mask, x, y))));
      const candidate = { size: base.size, cells, set(x, y, dark) { cells[y][x] = dark; } };
      format(candidate, mask);
      const score = penalty(cells);
      if (score < bestScore) { best = cells; bestScore = score; }
    }
    return best;
  }
  function svg(text, options = {}) {
    const matrix = encode(text), quiet = 4, width = matrix.length + quiet * 2;
    const parts = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${width}" role="img" aria-label="QR code for phone address"><rect width="${width}" height="${width}" fill="white"/>`];
    for (let y = 0; y < matrix.length; y++) for (let x = 0; x < matrix.length; x++) if (matrix[y][x]) parts.push(`<path d="M${x + quiet} ${y + quiet}h1v1h-1z" fill="black"/>`);
    parts.push('</svg>');
    return parts.join('');
  }
  globalThis.HubQR = Object.freeze({ encode, svg });
})();
