// UR0: optional Playwright screenshots for review. Written only when
// UI_SCREENSHOT_DIR is set (Product CI uploads that folder as an artifact).
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

export const SCREENSHOT_VIEWPORTS = Object.freeze([
  Object.freeze({ width: 1440, height: 900 }),
  Object.freeze({ width: 1920, height: 1080 }),
]);

export function screenshotDir(env = process.env) {
  const dir = env.UI_SCREENSHOT_DIR;
  return typeof dir === "string" && dir.trim() ? dir : null;
}

export function screenshotName(tab, { width, height }) {
  if (!/^[a-z0-9-]+$/.test(tab)) throw new Error(`Invalid screenshot name: ${tab}`);
  return `${tab}-${width}x${height}.png`;
}

export async function captureScreenshot(page, tab, viewport, dir = screenshotDir()) {
  if (!dir) return null;
  await mkdir(dir, { recursive: true });
  const path = join(dir, screenshotName(tab, viewport));
  await page.screenshot({ path, fullPage: true });
  return path;
}
