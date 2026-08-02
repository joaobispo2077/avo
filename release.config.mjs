import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const rootDir = dirname(fileURLToPath(import.meta.url));
const syncScript = join(rootDir, 'scripts/ci/sync-pyproject-version.mjs');

/** Keep Python package version aligned with semantic-release / package.json. */
function pyprojectVersionPlugin() {
  return {
    prepare(_pluginConfig, context) {
      const version = context.nextRelease.version;
      execFileSync(process.execPath, [syncScript, version], {
        cwd: rootDir,
        stdio: 'inherit',
      });
    },
  };
}

const analyzerOpts = {
  preset: 'angular',
  parserOpts: {
    noteKeywords: ['BREAKING CHANGE', 'BREAKING CHANGES', 'BREAKING'],
  },
  // Include commits merged via GitHub PR merges (not only merge commit messages).
  gitRawCommitsOpts: {
    firstParent: false,
  },
};

/** @type {import('semantic-release').Options} */
export default {
  branches: [
    'main',
    { name: 'develop', prerelease: 'alpha' },
  ],
  plugins: [
    ['@semantic-release/commit-analyzer', analyzerOpts],
    [
      '@semantic-release/release-notes-generator',
      {
        preset: 'angular',
        parserOpts: analyzerOpts.parserOpts,
        gitRawCommitsOpts: analyzerOpts.gitRawCommitsOpts,
        writerOpts: {
          commitsSort: ['subject', 'scope'],
        },
      },
    ],
    '@semantic-release/changelog',
    ['@semantic-release/npm', { npmPublish: false }],
    pyprojectVersionPlugin,
    '@semantic-release/github',
    [
      '@semantic-release/git',
      {
        assets: [
          'CHANGELOG.md',
          'package.json',
          'package-lock.json',
          'pyproject.toml',
        ],
        message:
          'chore(release): ${nextRelease.version}\n\n${nextRelease.notes}',
      },
    ],
  ],
};
