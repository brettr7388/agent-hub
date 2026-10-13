// Run with: node tests/qr_smoke.js
const assert = require('node:assert/strict');
require('../static/qr.js');

const samples = [
  '',
  'https://x.io/',
  'https://example.tail123.ts.net/',
  'https://example.tail123.ts.net/' + 'x'.repeat(60),
  'https://example.tail123.ts.net/' + 'x'.repeat(110),
  'https://example.tail123.ts.net/' + 'x'.repeat(170),
  'https://example.tail123.ts.net/' + 'x'.repeat(178),
  'Phone link ☎',
];
for (const sample of samples) {
  const matrix = HubQR.encode(sample);
  const size = matrix.length;
  assert(size >= 21 && size <= 57 && (size - 17) % 4 === 0);
  assert(matrix.every((row) => row.length === size && row.every((cell) => typeof cell === 'boolean')));
  assert(matrix[3][3] && matrix[3][size - 4] && matrix[size - 4][3]);
  assert.match(HubQR.svg(sample), /<svg[^>]*viewBox=/);
  console.log(`${size}×${size} ${sample.length} chars`);
}
assert.throws(() => HubQR.encode('x'.repeat(1200)), RangeError);
console.log('QR smoke passed');
