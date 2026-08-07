# Login Mascot Transparency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop login mascot's opaque beige rectangle with a reproducible `1024x1536` RGBA cutout that preserves the current character and integrates directly into the blue brand scene.

**Architecture:** A small Playwright/Canvas asset-generation script derives an alpha matte from the existing RGB source without redesigning the character, then writes a sibling PNG while retaining the original for rollback. `MascotFigure` changes only the full-size source constant, and login-scoped CSS removes the photo-frame treatment in favor of a contour-following drop shadow; mobile art direction continues to use the existing avatar.

**Tech Stack:** Node.js 22, Playwright 1.61, browser Canvas 2D, React 19, CSS, Node test runner, Vitest.

## Global Constraints

- Preserve the current character's face, hair, green hair clip, clothing, bag, book, pose, proportions, dark-blue halo, and green dot.
- Output `apps/web/public/assets/brand/mascot/cairn-mascot-transparent.png` as a `1024x1536` 8-bit RGBA PNG; do not overwrite `cairn-mascot.png`.
- Remove the beige backdrop, background glow, and floor shadow; do not add text, watermark, props, ground, or contact shadow.
- Keep `cairn-mascot-avatar.png` as the `max-width: 599px` source.
- Do not change authentication behavior, validation, error handling, APIs, focus management, page colors, wordmark, theme line, or form styling.

---

## File Structure

- Create `apps/web/scripts/generate-transparent-mascot.mjs`: reproducibly converts the checked-in RGB source into the checked-in RGBA asset using an exterior-background matte and edge despill.
- Create `apps/web/public/assets/brand/mascot/cairn-mascot-transparent.png`: desktop full-body mascot consumed by the app.
- Modify `apps/web/tests/web/mascot-assets.test.mjs`: owns binary asset requirements such as dimensions, channel type, and size budget.
- Modify `apps/web/tests/react/MascotFigure.test.tsx`: owns full-variant source selection and mobile art direction behavior.
- Modify `apps/web/src/components/MascotFigure.tsx`: owns the desktop full-variant asset URL.
- Modify `apps/web/tests/web/css-contract.test.mjs`: owns the login mascot's transparent-treatment CSS contract.
- Modify `apps/web/styles/main.css`: owns frame removal, contour shadow, and breakpoint-specific presentation.

### Task 1: Generate and validate the transparent mascot asset

**Files:**
- Create: `apps/web/scripts/generate-transparent-mascot.mjs`
- Create: `apps/web/public/assets/brand/mascot/cairn-mascot-transparent.png`
- Modify: `apps/web/tests/web/mascot-assets.test.mjs`

**Interfaces:**
- Consumes: `apps/web/public/assets/brand/mascot/cairn-mascot.png`, a `1024x1536` RGB PNG.
- Produces: `apps/web/public/assets/brand/mascot/cairn-mascot-transparent.png`, a `1024x1536` 8-bit RGBA PNG with transparent corners.
- Produces: `pnpm --filter cairn-web exec node scripts/generate-transparent-mascot.mjs`, a deterministic regeneration command.

- [ ] **Step 1: Add the failing binary asset contract**

Add a second URL and test to `mascot-assets.test.mjs`:

```js
const transparentFullUrl = new URL(
  "../../public/assets/brand/mascot/cairn-mascot-transparent.png",
  import.meta.url,
);

test("full mascot is a 1024x1536 RGBA PNG", async () => {
  const png = await readFile(transparentFullUrl);

  assert.deepEqual(png.subarray(0, 8), PNG_SIGNATURE);
  assert.equal(png.toString("ascii", 12, 16), "IHDR");
  assert.equal(png.readUInt32BE(16), 1024);
  assert.equal(png.readUInt32BE(20), 1536);
  assert.equal(png[24], 8, "full mascot must use 8-bit channels");
  assert.equal(png[25], 6, "full mascot must contain RGBA channels");
  assert.ok(png.byteLength < 2_500_000, "full mascot must stay below 2.5 MB");
});
```

- [ ] **Step 2: Run the asset test and verify the missing-file failure**

Run:

```bash
node --test apps/web/tests/web/mascot-assets.test.mjs
```

Expected: FAIL with `ENOENT` for `cairn-mascot-transparent.png`; the existing avatar test remains green.

- [ ] **Step 3: Implement deterministic Canvas background extraction**

Create `apps/web/scripts/generate-transparent-mascot.mjs` with the complete implementation below:

```js
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const inputPath = resolve(webRoot, "public/assets/brand/mascot/cairn-mascot.png");
const outputPath = resolve(webRoot, "public/assets/brand/mascot/cairn-mascot-transparent.png");

const input = await readFile(inputPath);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const dataUrl = await page.evaluate(async (sourceBase64) => {
    const source = `data:image/png;base64,${sourceBase64}`;
    const image = new Image();
    image.src = source;
    await image.decode();

    if (image.naturalWidth !== 1024 || image.naturalHeight !== 1536) {
      throw new Error(
        `Expected a 1024x1536 source, got ${image.naturalWidth}x${image.naturalHeight}`,
      );
    }

    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("Canvas 2D context is unavailable");

    context.drawImage(image, 0, 0);
    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    const { data, width, height } = frame;
    const pixelCount = width * height;
    const indexOf = (x, y) => y * width + x;
    const rgbaOffset = (index) => index * 4;
    const pixelAt = (index) => {
      const offset = rgbaOffset(index);
      return [data[offset], data[offset + 1], data[offset + 2]];
    };
    const median = (values) => {
      values.sort((a, b) => a - b);
      return values[Math.floor(values.length / 2)];
    };

    const borderSamples = [[], [], []];
    const borderDepth = 12;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        if (
          x >= borderDepth &&
          x < width - borderDepth &&
          y >= borderDepth &&
          y < height - borderDepth
        ) {
          continue;
        }
        const pixel = pixelAt(indexOf(x, y));
        borderSamples[0].push(pixel[0]);
        borderSamples[1].push(pixel[1]);
        borderSamples[2].push(pixel[2]);
      }
    }
    const background = borderSamples.map(median);
    const colorDistance = (pixel) => Math.hypot(
      pixel[0] - background[0],
      pixel[1] - background[1],
      pixel[2] - background[2],
    );
    const isBackgroundCandidate = (pixel) => {
      const maximum = Math.max(...pixel);
      const minimum = Math.min(...pixel);
      return maximum - minimum <= 45 && maximum >= 115 && colorDistance(pixel) <= 220;
    };

    const exterior = new Uint8Array(pixelCount);
    const queue = new Uint32Array(pixelCount);
    let queueHead = 0;
    let queueTail = 0;
    const enqueue = (x, y) => {
      const index = indexOf(x, y);
      if (exterior[index] || !isBackgroundCandidate(pixelAt(index))) return;
      exterior[index] = 1;
      queue[queueTail] = index;
      queueTail += 1;
    };

    for (let x = 0; x < width; x += 1) {
      enqueue(x, 0);
      enqueue(x, height - 1);
    }
    for (let y = 1; y < height - 1; y += 1) {
      enqueue(0, y);
      enqueue(width - 1, y);
    }

    while (queueHead < queueTail) {
      const index = queue[queueHead];
      queueHead += 1;
      const x = index % width;
      const y = Math.floor(index / width);
      if (x > 0) enqueue(x - 1, y);
      if (x + 1 < width) enqueue(x + 1, y);
      if (y > 0) enqueue(x, y - 1);
      if (y + 1 < height) enqueue(x, y + 1);
    }

    const touchesExterior = (x, y) => {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
          if (offsetX === 0 && offsetY === 0) continue;
          const neighborX = x + offsetX;
          const neighborY = y + offsetY;
          if (
            neighborX >= 0 &&
            neighborX < width &&
            neighborY >= 0 &&
            neighborY < height &&
            exterior[indexOf(neighborX, neighborY)]
          ) {
            return true;
          }
        }
      }
      return false;
    };

    let transparentPixels = 0;
    let opaquePixels = 0;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const index = indexOf(x, y);
        const offset = rgbaOffset(index);
        if (exterior[index]) {
          data[offset + 3] = 0;
          transparentPixels += 1;
          continue;
        }

        if (touchesExterior(x, y)) {
          const distance = colorDistance(pixelAt(index));
          const alpha = Math.max(0, Math.min(1, (distance - 18) / 92));
          if (alpha < 1) {
            data[offset + 3] = Math.round(alpha * 255);
            for (let channel = 0; channel < 3; channel += 1) {
              const recovered =
                (data[offset + channel] - background[channel] * (1 - alpha)) /
                Math.max(alpha, 0.01);
              data[offset + channel] = Math.max(0, Math.min(255, Math.round(recovered)));
            }
          }
        }

        if (data[offset + 3] >= 250) opaquePixels += 1;
      }
    }

    const transparentRatio = transparentPixels / pixelCount;
    const opaqueRatio = opaquePixels / pixelCount;
    if (transparentRatio < 0.45 || transparentRatio > 0.85) {
      throw new Error(`Unexpected transparent coverage: ${transparentRatio.toFixed(3)}`);
    }
    if (opaqueRatio < 0.12 || opaqueRatio > 0.55) {
      throw new Error(`Unexpected opaque coverage: ${opaqueRatio.toFixed(3)}`);
    }
    for (const [x, y] of [
      [0, 0],
      [width - 1, 0],
      [0, height - 1],
      [width - 1, height - 1],
    ]) {
      if (data[rgbaOffset(indexOf(x, y)) + 3] !== 0) {
        throw new Error(`Corner ${x},${y} is not transparent`);
      }
    }

    context.putImageData(frame, 0, 0);
    return canvas.toDataURL("image/png");
  }, input.toString("base64"));
  await writeFile(outputPath, Buffer.from(dataUrl.split(",")[1], "base64"));
} finally {
  await browser.close();
}
```

Run:

```bash
pnpm --filter cairn-web exec node scripts/generate-transparent-mascot.mjs
```

- [ ] **Step 4: Validate the generated alpha asset**

Run the contract again:

```bash
node --test apps/web/tests/web/mascot-assets.test.mjs
```

Expected: PASS for both avatar and full mascot contracts.

Open the generated PNG with the local image viewer and inspect it against both `#ffffff` and `#1f4b86` backgrounds. Confirm:

- all four corners and the space around the character are transparent;
- the beige rectangle, glow, and floor shadow are gone;
- face, hair strands, white sleeves, legs, halo, and green dot remain intact;
- there is no visible beige fringe at hair, sleeves, shoes, halo, or props.

If the exterior flood misses an enclosed beige region, add an explicit seed at the center of that region and regenerate. If it touches any character pixel, tighten only that seed's candidate threshold; do not paint over the subject.

- [ ] **Step 5: Commit the reproducible asset deliverable**

```bash
git add apps/web/scripts/generate-transparent-mascot.mjs \
  apps/web/public/assets/brand/mascot/cairn-mascot-transparent.png \
  apps/web/tests/web/mascot-assets.test.mjs
git commit -m "feat(web): add transparent full mascot asset"
```

### Task 2: Point the full mascot variant at the transparent asset

**Files:**
- Modify: `apps/web/tests/react/MascotFigure.test.tsx`
- Modify: `apps/web/src/components/MascotFigure.tsx`

**Interfaces:**
- Consumes: `/assets/brand/mascot/cairn-mascot-transparent.png` from Task 1.
- Preserves: mobile `<source media="(max-width: 599px)">` using `/assets/brand/mascot/cairn-mascot-avatar.png`.
- Preserves: existing primary -> Cairn logo -> accessible fallback state machine.

- [ ] **Step 1: Change the React expectation first**

In `MascotFigure.test.tsx`, update only the full-variant desktop `src` expectation:

```tsx
expect(screen.getByRole("img", { name: "看板娘" })).toHaveAttribute(
  "src",
  "/assets/brand/mascot/cairn-mascot-transparent.png",
);
```

- [ ] **Step 2: Verify the focused React test fails**

Run:

```bash
pnpm --filter cairn-web exec vitest run tests/react/MascotFigure.test.tsx
```

Expected: one failure showing the current `/assets/brand/mascot/cairn-mascot.png` URL; mobile source and fallback tests remain green.

- [ ] **Step 3: Update the source constant**

In `MascotFigure.tsx`:

```ts
const MASCOT_FULL_SRC = "/assets/brand/mascot/cairn-mascot-transparent.png";
```

Do not change `MASCOT_AVATAR_SRC`, `FALLBACK_SRC`, the `<source>` condition, or the error-stage transition.

- [ ] **Step 4: Verify component behavior**

Run:

```bash
pnpm --filter cairn-web exec vitest run tests/react/MascotFigure.test.tsx
```

Expected: all `MascotFigure` and neighboring `WorkspaceStatus` tests PASS.

- [ ] **Step 5: Commit the source switch**

```bash
git add apps/web/src/components/MascotFigure.tsx apps/web/tests/react/MascotFigure.test.tsx
git commit -m "feat(web): use transparent mascot on login"
```

### Task 3: Remove the photo frame and apply a contour shadow

**Files:**
- Modify: `apps/web/tests/web/css-contract.test.mjs`
- Modify: `apps/web/styles/main.css`

**Interfaces:**
- Consumes: transparent full-size image from Task 1 through `MascotFigure` from Task 2.
- Produces: login-scoped desktop/tablet presentation with no background, padding, frame shadow, or rotation.
- Preserves: mobile circular avatar dimensions and all non-login mascot styles.

- [ ] **Step 1: Add the failing transparent-treatment CSS contract**

Add this test to `css-contract.test.mjs`:

```js
test("login full mascot uses transparent artwork instead of a photo frame", async () => {
  const css = await readFile(cssUrl, "utf8");
  const rule = css.match(
    /\.login-brand-scene \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-art\s*>\s*img,\s*\.login-brand-scene \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-image-fallback\s*\{([^}]*)\}/,
  );

  assert.ok(rule, "missing login full mascot rule");
  assert.match(rule[1], /padding:\s*0/);
  assert.match(rule[1], /border:\s*0/);
  assert.match(rule[1], /background:\s*transparent/);
  assert.match(rule[1], /filter:\s*drop-shadow\(/);
  assert.match(rule[1], /transform:\s*none/);
  assert.doesNotMatch(rule[1], /box-shadow:/);
});
```

- [ ] **Step 2: Verify the CSS contract fails on the frame styling**

Run:

```bash
node --test apps/web/tests/web/css-contract.test.mjs
```

Expected: FAIL because the current desktop rule has padded photo-paper styling, `box-shadow`, and `rotate(-2deg)`.

- [ ] **Step 3: Replace desktop/tablet frame declarations**

Keep the current width and height constraints, but replace the frame declarations in `main.css` with:

```css
.login-brand-scene .mascot-figure[data-variant='full'] .mascot-art > img,
.login-brand-scene .mascot-figure[data-variant='full'] .mascot-image-fallback {
  width: min(260px, 78%);
  height: min(390px, 48vh);
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  filter: drop-shadow(0 14px 18px rgb(6 18 36 / 34%));
  transform: none;
  object-fit: contain;
  object-position: center;
}
```

Replace the obsolete frame explanation with a short comment stating that the RGBA asset is composited directly onto the brand scene and the shadow follows its alpha contour. Keep the tablet width/height override unchanged.

In the mobile rule, remove the stale comment contrasting transparent mobile and opaque desktop artwork. Preserve `82px` square sizing, `border-radius: 50%`, and the avatar's compact shadow. Add `filter: none` there so the desktop contour shadow cannot stack with the mobile avatar shadow.

- [ ] **Step 4: Verify the CSS contract and full Web suite**

Run:

```bash
node --test apps/web/tests/web/css-contract.test.mjs
pnpm --filter cairn-web test
```

Expected: CSS contract PASS; all Web unit and React tests PASS.

- [ ] **Step 5: Commit the presentation change**

```bash
git add apps/web/styles/main.css apps/web/tests/web/css-contract.test.mjs
git commit -m "style(web): blend login mascot into brand scene"
```

### Task 4: Cross-theme visual and production verification

**Files:**
- Modify only if a failing verification exposes an in-scope defect in the files listed above.

**Interfaces:**
- Consumes: completed asset, source selection, and transparent presentation from Tasks 1-3.
- Produces: evidence that the login page is stable across target viewports, themes, tests, type checking, and production bundling.

- [ ] **Step 1: Run static and build verification**

```bash
pnpm --filter cairn-web test
pnpm --filter cairn-web typecheck
pnpm --filter cairn-web build
```

Expected: all commands exit `0`.

- [ ] **Step 2: Inspect the running login page across viewports**

Using the existing dev server at `http://localhost:5500/login`, capture light and dark screenshots at:

- desktop: `1440x900`;
- tablet: `768x1024`;
- mobile: `390x844`.

For desktop and tablet, verify that Canvas pixels immediately outside the character are the blue scene color rather than beige/white; verify the character occupies the same stable layout footprint as before. For mobile, verify that the existing avatar is still circular and does not inherit the desktop contour shadow.

- [ ] **Step 3: Check visual acceptance criteria**

Confirm from the screenshots:

- no rectangular background, photo-paper padding, white edge, or `-2deg` rotation remains;
- the full character, halo, green dot, bag, book, shoes, and fine hair edges are visible;
- the contour shadow is subtle and follows the silhouette;
- status text, wordmark, login card, decorative triangles, and form controls do not overlap;
- all text and controls fit at every viewport.

If an alpha defect appears, fix the generator thresholds/seeds and regenerate the PNG; if a layout defect appears, adjust only the login-scoped image sizing. Re-run the focused contract before returning to this checklist.

- [ ] **Step 4: Run the repository core gate**

Use the already configured local PostgreSQL override if port `5432` remains occupied:

```bash
CAIRN_POSTGRES_PORT=55432 \
DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55432/cairn \
pnpm verify:core
```

Expected: every core verification stage exits `0`.

- [ ] **Step 5: Commit any verification-only correction**

Skip this step if verification required no edits. Otherwise stage only the in-scope corrected files and commit:

```bash
git add apps/web/public/assets/brand/mascot/cairn-mascot-transparent.png \
  apps/web/scripts/generate-transparent-mascot.mjs \
  apps/web/src/components/MascotFigure.tsx \
  apps/web/styles/main.css \
  apps/web/tests/react/MascotFigure.test.tsx \
  apps/web/tests/web/mascot-assets.test.mjs \
  apps/web/tests/web/css-contract.test.mjs
git commit -m "fix(web): refine transparent mascot rendering"
```
