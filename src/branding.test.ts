import { existsSync, readFileSync } from 'fs';
import path from 'path';

const publicDirectory = path.resolve(__dirname, '../public');
const html = readFileSync(path.join(publicDirectory, 'index.html'), 'utf8');
const manifest = JSON.parse(readFileSync(path.join(publicDirectory, 'manifest.json'), 'utf8'));

test('the browser tab and installed app use Thrivewell branding', () => {
  const document = new DOMParser().parseFromString(html, 'text/html');
  expect(document.title).toBe('Thrivewell');
  expect(document.querySelector('link[rel="icon"][type="image/svg+xml"]')?.getAttribute('href')).toBe('%PUBLIC_URL%/thrivewell-icon.svg');
  expect(document.querySelector('link[rel="icon"][type="image/x-icon"]')?.getAttribute('href')).toBe('%PUBLIC_URL%/favicon.ico?v=thrivewell-1');
  expect(document.querySelector('link[rel="apple-touch-icon"]')?.getAttribute('href')).toBe('%PUBLIC_URL%/logo192.png?v=thrivewell-1');
  expect(manifest.name).toBe('Thrivewell');
  expect(manifest.short_name).toBe('Thrivewell');
  expect(manifest.theme_color).toBe(document.querySelector('meta[name="theme-color"]')?.getAttribute('content'));
  expect(manifest.start_url).toBe('.');
});

test('every declared branding asset exists and the PNG sizes match the manifest', () => {
  const document = new DOMParser().parseFromString(html, 'text/html');
  document.querySelectorAll('link[rel="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]').forEach(link => {
    const filename = link.getAttribute('href')!.replace('%PUBLIC_URL%/', '').split('?')[0];
    expect(existsSync(path.join(publicDirectory, filename))).toBe(true);
  });
  manifest.icons.forEach((icon: { src: string; type: string; sizes: string }) => {
    const filename = path.join(publicDirectory, icon.src.split('?')[0]);
    expect(existsSync(filename)).toBe(true);
    if (icon.type === 'image/png') {
      const bytes = readFileSync(filename);
      expect(bytes.subarray(1, 4).toString()).toBe('PNG');
      expect(`${bytes.readUInt32BE(16)}x${bytes.readUInt32BE(20)}`).toBe(icon.sizes);
    }
  });
});

test('the fallback favicon contains all declared browser sizes', () => {
  const bytes = readFileSync(path.join(publicDirectory, 'favicon.ico'));
  expect(bytes.readUInt16LE(0)).toBe(0);
  expect(bytes.readUInt16LE(2)).toBe(1);
  const count = bytes.readUInt16LE(4);
  const sizes = Array.from({ length: count }, (_, index) => `${bytes[6 + index * 16]}x${bytes[7 + index * 16]}`);
  expect(sizes.sort()).toEqual(manifest.icons[0].sizes.split(' ').sort());
});
