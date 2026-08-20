import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const rootDir = fileURLToPath(new URL('../../', import.meta.url));

function updateJsonVersion(relPath, version) {
  const path = join(rootDir, relPath);
  const raw = readFileSync(path, 'utf8');
  const data = JSON.parse(raw);
  if (data.version === version) {
    return false;
  }
  data.version = version;
  writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  return true;
}

/**
 * Lightweight substitute for `@semantic-release/npm` when `npmPublish` is false.
 * Updates package.json (+ lockfile version field) without depending on the `npm`
 * package (whose bundledDependencies currently carry high-severity advisories).
 */
export default {
  prepare(_pluginConfig, context) {
    const version = context.nextRelease.version;
    const pkgChanged = updateJsonVersion('package.json', version);
    const lockChanged = updateJsonVersion('package-lock.json', version);
    if (pkgChanged || lockChanged) {
      context.logger.log(
        `Updated package manifests to version ${version} (package.json` +
          `${lockChanged ? ' + package-lock.json' : ''})`,
      );
    } else {
      context.logger.log(`package manifests already at version ${version}`);
    }
  },
};
