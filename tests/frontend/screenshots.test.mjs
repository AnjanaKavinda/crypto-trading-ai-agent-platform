import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { SCREENSHOT_VIEWPORTS, screenshotDir, screenshotName } from "./screenshots.mjs";

test("screenshots are opt-in, at the two review viewports, with safe names", () => {
  assert.equal(screenshotDir({}), null);
  assert.equal(screenshotDir({ UI_SCREENSHOT_DIR: "  " }), null);
  assert.equal(screenshotDir({ UI_SCREENSHOT_DIR: "out" }), "out");
  assert.deepEqual(SCREENSHOT_VIEWPORTS.map(({ width, height }) => `${width}x${height}`), ["1440x900", "1920x1080"]);
  assert.equal(screenshotName("strategy-lab", SCREENSHOT_VIEWPORTS[0]), "strategy-lab-1440x900.png");
  assert.throws(() => screenshotName("../x", SCREENSHOT_VIEWPORTS[0]), /Invalid screenshot name/);
});

test("Product CI uploads the screenshot folder with a pinned action and no other change in behaviour", async () => {
  const workflow = await readFile(new URL("../../.github/workflows/product-ci.yml", import.meta.url), "utf8");
  assert.match(workflow, /UI_SCREENSHOT_DIR: \$\{\{ runner\.temp \}\}\/ui-screenshots/);
  assert.match(workflow, /uses: actions\/upload-artifact@[0-9a-f]{40} # v4\.6\.2/);
  assert.match(workflow, /name: ui-screenshots/);
  assert.doesNotMatch(workflow, /continue-on-error/);
});
