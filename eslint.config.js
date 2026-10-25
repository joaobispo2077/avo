import js from '@eslint/js';
import prettier from 'eslint-plugin-prettier';
import eslintConfigPrettier from 'eslint-config-prettier';
import { flatConfigs as importXConfigs } from 'eslint-plugin-import-x';
import sonarjs from 'eslint-plugin-sonarjs';
import globals from 'globals';
import tseslint from 'typescript-eslint';

/** AVO Node glue surfaces (FR-3). Exemplars stay under hyperframes lint. */
const jsGlobs = [
  'bin/**/*.{js,cjs,mjs}',
  'scripts/**/*.{js,cjs,mjs}',
  'helpers/**/*.mjs',
  'release.config.mjs',
  'eslint.config.js',
];

const tsGlobs = [
  'bin/**/*.ts',
  'configs/**/*.ts',
  'lib/**/*.ts',
  'tests/infra/**/*.ts',
];

const scoped = [...jsGlobs, ...tsGlobs];

function withFiles(config, files = scoped) {
  if (Array.isArray(config)) {
    return config.map((entry) => withFiles(entry, files));
  }
  return { ...config, files };
}

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**',
      '**/.venv/**',
      '**/venv/**',
      '**/dist/**',
      '**/coverage/**',
      '**/.coverage/**',
      '**/tmp/**',
      '**/.tmp/**',
      '**/.sdd/**',
      '**/.cursor/**',
      '**/.avo/**',
      '**/.git/**',
      '**/docs/exemplars/**',
      '**/.mutmut-cache/**',
      '**/htmlcov/**',
      '**/stryker-tmp/**',
      '**/reports/**',
      '**/providers/**',
      '**/src/**',
      '**/skills/**',
      '**/.agents/**',
      '**/commands/**',
      '**/specs/**',
      '**/tests/**',
      'package-lock.json',
      'uv.lock',
    ],
  },
  withFiles(js.configs.recommended),
  withFiles(importXConfigs.recommended),
  withFiles(sonarjs.configs.recommended),
  {
    files: scoped,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.node,
      },
    },
    settings: {
      'import-x/resolver': {
        node: {
          extensions: ['.js', '.cjs', '.mjs', '.ts', '.cts', '.mts'],
        },
      },
    },
    plugins: {
      prettier,
    },
    rules: {
      complexity: ['error', { max: 12 }],
      'sonarjs/cognitive-complexity': ['error', 15],
      'prettier/prettier': 'warn',
      'no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
  {
    files: ['bin/**/*.cjs', 'scripts/**/*.cjs'],
    languageOptions: {
      sourceType: 'commonjs',
      globals: {
        ...globals.node,
      },
    },
  },
  {
    files: tsGlobs,
    extends: [tseslint.configs.recommended],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
  withFiles(eslintConfigPrettier),
);
