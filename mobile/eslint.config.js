// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require("eslint-config-expo/flat");

const NO_PURCHASES = 'Elders never see purchase UI (CLAUDE.md §1, §10).';

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["dist/*"],
  },
  {
    // Elder mode: no purchase code can even be imported, so no purchase UI can ever render.
    files: ["src/app/home/**", "src/components/elder.tsx"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            { name: "react-native-purchases", message: NO_PURCHASES },
            { name: "react-native-purchases-ui", message: NO_PURCHASES },
            { name: "@/components/plus", message: NO_PURCHASES },
          ],
          patterns: [{ group: ["@/billing/*"], message: NO_PURCHASES }],
        },
      ],
    },
  },
]);
