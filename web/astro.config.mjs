import { defineConfig } from "astro/config";

// BASE_PATH lets GitHub Pages serve the site from /<repo-name>/.
export default defineConfig({
  site: process.env.SITE_URL,
  base: process.env.BASE_PATH || "/",
  trailingSlash: "ignore",
});
