// Fails if src/api/schema.d.ts is out of date with backend/openapi.json.
// openapi-typescript runs through a pinned npx copy: it needs TypeScript 5 while the app uses 6
// (the generated .d.ts works with both).
import { execSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = mkdtempSync(join(tmpdir(), 'nodly-api-'));
const fresh = join(dir, 'schema.d.ts');
try {
  // One command string: npx is a .cmd on Windows and needs a shell, and Node deprecates passing
  // an args array together with `shell` (DEP0190).
  execSync(`npx --yes openapi-typescript@7.13.0 ../backend/openapi.json -o "${fresh}"`, {
    stdio: 'ignore',
  });
  const normalize = (text) => text.replace(/\r\n/g, '\n');
  const current = normalize(readFileSync('src/api/schema.d.ts', 'utf8'));
  if (normalize(readFileSync(fresh, 'utf8')) !== current) {
    console.error('src/api/schema.d.ts is out of date: run npm run gen:api');
    process.exit(1);
  }
  console.log('src/api/schema.d.ts is up to date');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
