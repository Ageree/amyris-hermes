import js from "@eslint/js";
import tseslint from "typescript-eslint";
import unusedImports from "eslint-plugin-unused-imports";

const tsFiles = ["**/*.{ts,tsx}"];
const jsFiles = ["**/*.{js,mjs,cjs}"];

const nodeGlobals = {
  AbortController: "readonly",
  Buffer: "readonly",
  TextDecoder: "readonly",
  URL: "readonly",
  __dirname: "readonly",
  clearInterval: "readonly",
  clearTimeout: "readonly",
  console: "readonly",
  fetch: "readonly",
  process: "readonly",
  require: "readonly",
  setInterval: "readonly",
  setTimeout: "readonly",
};

const browserGlobals = {
  document: "readonly",
  fetch: "readonly",
  window: "readonly",
};

export default [
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/.output/**",
      "**/dist/**",
      "**/build/**",
      "**/coverage/**",
      "**/test-results/**",
      "**/playwright-report/**",
      "**/cp-generated/**",
      "agent/.eve/**",
      "control-plane/convex/_generated/**",
      "features/**",
      "**/*.tsbuildinfo",
      ".agents/**",
      ".claude/**",
      ".gitnexus/**",
      "docs/overnight/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: [...tsFiles, ...jsFiles],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: nodeGlobals,
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    rules: {
      complexity: ["warn", { max: 12 }],
      "max-depth": ["warn", 4],
      "max-lines": ["warn", { max: 450, skipBlankLines: true, skipComments: true }],
      "max-params": ["warn", 5],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "no-empty": ["warn", { allowEmptyCatch: true }],
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": "off",
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/.env*", "**/secrets.*", "**/private/**"],
              message: "Do not import secrets or private environment files.",
            },
          ],
        },
      ],
      "unused-imports/no-unused-imports": "warn",
    },
    plugins: {
      "unused-imports": unusedImports,
    },
  },
  {
    files: tsFiles,
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: {
          allowDefaultProject: [
            "web/e2e/*.ts",
            "web/e2e/*.spec.ts",
            "control-plane/scripts/*.ts",
          ],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "@typescript-eslint": tseslint.plugin,
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": [
        "warn",
        { fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/explicit-function-return-type": [
        "warn",
        {
          allowExpressions: true,
          allowTypedFunctionExpressions: true,
        },
      ],
      "@typescript-eslint/naming-convention": [
        "warn",
        {
          selector: "default",
          format: ["camelCase"],
          leadingUnderscore: "allow",
          trailingUnderscore: "allow",
        },
        {
          selector: ["typeLike", "enumMember"],
          format: ["PascalCase"],
        },
        {
          selector: ["variable"],
          modifiers: ["const"],
          format: ["camelCase", "PascalCase", "UPPER_CASE"],
          leadingUnderscore: "allow",
        },
        {
          selector: ["property"],
          modifiers: ["requiresQuotes"],
          format: null,
        },
        {
          selector: ["property", "method"],
          format: ["camelCase", "PascalCase"],
          leadingUnderscore: "allow",
        },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-empty-object-type": "warn",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "warn",
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/triple-slash-reference": "warn",
    },
  },
  {
    files: ["control-plane/convex_e2e/**/*.mjs", "control-plane/drainer/**/*.mjs"],
    languageOptions: {
      globals: { ...browserGlobals, ...nodeGlobals },
    },
    rules: {
      "no-console": "off",
    },
  },
  {
    files: ["web/**/*.{ts,tsx}"],
    languageOptions: {
      globals: browserGlobals,
    },
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: ["../agent/**", "../control-plane/**", "../fleet/**", "../lab/**"],
        },
      ],
    },
  },
  {
    files: ["control-plane/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: ["../agent/**", "../web/**", "../fleet/**", "../lab/**"],
        },
      ],
    },
  },
  {
    files: ["agent/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: ["../control-plane/**", "../web/**", "../fleet/**", "../lab/**"],
        },
      ],
    },
  },
  {
    files: [
      "*.config.mjs",
      "scripts/**/*.mjs",
      "lab/photon-sidecar/**/*.mjs",
      "agent/scripts/**/*.ts",
    ],
    rules: {
      "no-console": "off",
    },
  },
  {
    files: ["lab/photon-sidecar/**/*.{mjs,js}"],
    languageOptions: {
      sourceType: "commonjs",
    },
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "no-undef": "off",
    },
  },
];
