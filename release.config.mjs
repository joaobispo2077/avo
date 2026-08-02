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
  branches: ['release'],
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
    './scripts/ci/semantic-release-pyproject-version.mjs',
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
