import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  build: { target: "es2022", cssCodeSplit: false, modulePreload: { polyfill: false } },
  // `npm run dev` reads live data from a running bot, e.g. through an SSH tunnel: ssh -L 8794:127.0.0.1:8794 your-server
  server: { proxy: { "/ships.json": "http://127.0.0.1:8794", "/img": "http://127.0.0.1:8794" } },
});
