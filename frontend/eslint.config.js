import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import prettier from "eslint-config-prettier";
import tseslint from "typescript-eslint";
import svelteConfig from "./svelte.config.js";

/**
 * Flat config, deliberately arranged so the TypeScript conversion is an
 * addition rather than a rewrite: the JS and Svelte blocks below already carry
 * the project rules, and `typescript-eslint` slots in as one more block once
 * there are `.ts` files for it to type-check.
 *
 * Formatting is Prettier's job alone. `eslint-config-prettier` is last on
 * purpose — it switches off every stylistic rule ESLint would otherwise argue
 * with Prettier about, so the two tools can never disagree about a file.
 */
export default [
  { ignores: ["node_modules/**", "dist/**", "../partyline/static/**"] },

  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked.map((config) => ({
    ...config,
    files: ["**/*.ts"],
  })),
  ...tseslint.configs.stylisticTypeChecked.map((config) => ({
    ...config,
    files: ["**/*.ts"],
  })),
  ...svelte.configs["flat/recommended"],

  {
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      globals: {
        ...globals.browser,
        // Injected by Vite at build time; see frontend/vite.config.js.
        __PARTYLINE_BUILD__: "readonly",
      },
    },
    rules: {
      // `{@html}` is a real hazard and every use should have to justify itself.
      // The one legitimate use is a message body, which `renderMessage` escapes
      // and sanitises; it is opted in explicitly at that call site.
      "svelte/no-at-html-tags": "error",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],
      eqeqeq: ["error", "smart"],
      "prefer-const": "error",
      "no-var": "error",
      "object-shorthand": "error",
    },
  },

  {
    files: ["**/*.ts"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],
    },
  },

  {
    files: ["**/*.svelte", "**/*.svelte.js", "**/*.svelte.ts"],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, svelteConfig },
    },
    rules: {
      // Core `prefer-const` is actively wrong in a Svelte 5 component: props are
      // declared `let { … } = $props()` and reassigned by the framework, not by
      // us, so it "fixes" them into `const` and breaks reactivity. The plugin's
      // version understands runes and only flags the genuinely constant.
      "prefer-const": "off",
      "svelte/prefer-const": ["error", { destructuring: "all" }],
      // `placeholder={"a\nb"}` looks redundant but is not: an attribute cannot
      // carry a newline escape any other way.
      "svelte/no-useless-mustaches": ["error", { ignoreStringEscape: true }],
    },
  },

  {
    // Config and build files run in Node, not the browser.
    files: ["*.config.js"],
    languageOptions: { globals: { ...globals.node } },
  },

  {
    files: ["**/*.test.{js,ts}"],
    languageOptions: { globals: { ...globals.node } },
  },

  prettier,
];
