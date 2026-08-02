import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const rootDir = dirname(fileURLToPath(new URL('../../', import.meta.url)));
const syncScript = join(rootDir, 'scripts/ci/sync-pyproject-version.mjs');

/** Keep Python package version aligned with semantic-release / package.json. */
export default {
  prepare(_pluginConfig, context) {
    const version = context.nextRelease.version;
    execFileSync(process.execPath, [syncScript, version], {
      cwd: rootDir,
      stdio: 'inherit',
    });
  },
};
