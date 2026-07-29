import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { astryxStylex, LIGHTNINGCSS_TARGETS } from "@astryxdesign/build/vite";

export default defineConfig({
  base: "./",
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "react-vendor",
              test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/,
            },
          ],
        },
      },
    },
  },
  plugins: [
    ...astryxStylex({ lightningcssTargets: LIGHTNINGCSS_TARGETS }),
    react(),
  ],
  clearScreen: false,
  server: {
    strictPort: true,
  },
});
