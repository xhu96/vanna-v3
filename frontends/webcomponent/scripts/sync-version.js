/** Verify the immutable Python/npm version contract without mutating sources. */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const rootDirectory = path.join(scriptDirectory, '../../..');

function projectVersion() {
  const content = fs.readFileSync(path.join(rootDirectory, 'pyproject.toml'), 'utf8');
  const match = content.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error('Could not find project.version in pyproject.toml');
  }
  return match[1];
}

function jsonVersion(relativePath, selector = (value) => value.version) {
  const value = JSON.parse(
    fs.readFileSync(path.join(rootDirectory, relativePath), 'utf8')
  );
  return selector(value);
}

function main() {
  const versions = {
    pyproject: projectVersion(),
    package: jsonVersion('frontends/webcomponent/package.json'),
    lockfile: jsonVersion(
      'frontends/webcomponent/package-lock.json',
      (value) => value.packages[''].version
    ),
  };
  const unique = new Set(Object.values(versions));
  if (unique.size !== 1 || versions.pyproject !== '3.3.0') {
    throw new Error(`Version contract mismatch: ${JSON.stringify(versions)}`);
  }
  console.log(`Version contract verified: ${versions.pyproject}`);
}

try {
  main();
} catch (error) {
  console.error(`Version verification failed: ${error.message}`);
  process.exit(1);
}
