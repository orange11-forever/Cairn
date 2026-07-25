# Handoff

## State
I completed Day 4 async JavaScript. `practice/day4/` now has a real Node mock backend (`mock-server.mjs`, port 8787, switchable via `?scenario=`), a unified request layer (`api-client.js`) with AbortController timeout/cancel and a four-kind `ApiError` (network/http/timeout/aborted), and a six-state state-machine document loader (`app.js` + `index.html`).
I verified the backend with curl (200/`[]`/500/5s all correct), the request layer end-to-end in Node (all six kinds), AND the full UI in a real headless Chromium via Playwright (`practice/day4/verify-browser.mjs`) — 8 frames all pass with screenshots in `practice/day4/screenshots/`. Installing Playwright required `sudo npx playwright install-deps chromium` (WSL was missing libnss3/libnspr4 etc.); playwright@1.61.1 is now a devDependency.
I rewrote the blog for beginners (`docs/blog/2026-07-24-async-javascript.md`, C++ angle removed, added intro sections on why-async/Promise/async-await) and PUBLISHED it as **post 989**: https://xiaochublog.top/async-javascript-promise-fetch/ — category Web开发(19), featured image attachment 992 (a Yuuka cover the user picked), full content verified live via public REST (10667 chars, no corruption). Published via the write-file-to-theme + WPCode snippet route (same as Day 3) because the 17.8KB CJK body exceeds both rest_api body and run_wp_cli base64 limits.
Tags: only 3 of 5 attached (javascript, 前端入门, promise). The other two (异步编程, async-await) could NOT be created — the wpvibe `rest_api` POST `body` param is non-deterministically parsed into an object by the harness ("expected string, received object"), so tag creation kept failing. If the user wants all 5 tags, create the two terms via a WPCode snippet with wp_insert_term, then `post term set 989 post_tag ... --by=slug`.
Cleanup DONE: temp files day4-part1/2.html deleted; WPCode snippet #990 deactivated (active=false, code replaced with a no-op). WPCode plugin itself stays installed/enabled.
Day 3 (JS core, published as post 975) and Day 2 (CSS, post 964) are done.

## Day 5 progress (2026-07-25, session was interrupted once — this section is the truth)
DONE:
- `apps/web/` rebuilt as real ES Modules from an empty dir: `src/api/{client,documents,errors}.js`, `src/lib/documents.js` (pure transforms), `src/state/documentStore.js`, `src/ui/{statusBar,documentList}.js`, `src/main.js`, `styles/main.css`, `index.html`.
- Support scripts: `mocks/docs-server.mjs` (port 8787, `?scenario=`), `scripts/serve-web.mjs` (port 5500), `scripts/verify-web.mjs` (Playwright, 8 frames, asserts zero JS-layer console errors and whitelists the deliberate 500/offline network logs).
- Static tests `tests/web/html-structure.test.mjs` + `tests/web/css-contract.test.mjs`.
- **Acceptance item "add a test for one data-transform function": DONE** — `tests/web/documents-transform.test.mjs`, 19 tests over `normalizeDocuments`/`filterByStatus`/`countByStatus`/`statusLabel`.
- `practice/day5-review.md` written (section-8 template).
- Those tests found TWO real prototype-chain bugs in `src/lib/documents.js`, both fixed: `statusLabel('toString')` returned `Object.prototype.toString` (a function) because `obj[key] ?? fallback` walks the prototype chain — now uses `Object.hasOwn`; `countByStatus` had the same hole and produced a string-concatenated count — the tally object is now `Object.create(null)`.
- Verified: `pnpm test` = 47 tests, 46 pass; `node scripts/verify-web.mjs` = 8/8 frames pass, zero JS errors.

REMAINING for Day 5:
1. `practice/day5-review.md` — daily review using the curriculum's section-8 template.
2. Day 5 blog draft in `docs/blog/` (beginner-facing, no C++ contrast; use the `blog-to-wordpress` skill to publish, needs explicit approval).
3. Git branch + clean commits — this is an explicit Day 5 learning topic and the repo is still on unborn `main` with everything untracked. NEEDS EXPLICIT AUTHORIZATION before any commit.
4. Project demo / first-phase acceptance walkthrough.

## Next
1. Finish the four Day 5 remaining items above.
2. PRE-EXISTING FAILURE, unrelated to Day 5: `tests/wordpress-build-posts.test.mjs` fails because the `async-javascript-promise-fetch` entry in `scripts/wordpress/posts.config.mjs` lacks `coverPath`/`coverAlt` (post 989 used the user-picked Yuuka cover, attachment 992, never saved into `assets/blog/`). Either save the cover locally + add both fields, or relax the assertion for already-published posts.
3. Day 4 blog was already published as post 989 (the older "not published" note was stale).
4. Recheck the `wpmu.php` null guard after any Colibri Page Builder update.

## Context
SCOPE DECISION (2026-07-25): the 35-day scope stays as written; a ~60-day Phase 2 afterwards extends Tracebase into Feishu/Glean-style enterprise search. Day 17 must build `documents` as a general `resources` table with `source_type`, `source_id`, `external_id` (unique with source_id, for ingest idempotency), `source_updated_at`, `acl_principals text[]` + GIN index, and `metadata JSONB` — even though only the `upload` source exists then. Day 24 retrieval takes a `source_type` filter.
The learner works in vibe-coding mode: he does not hand-write the code. Assess explain-line-by-line, code review, spec definition, and verification instead of from-scratch typing; the no-merging-code-you-cannot-explain rule still holds.
The authoritative curriculum is `/mnt/e/AI_Fullstack_35_Day_Plan.md` (Day 4 = 事件循环/Promise/async-await/Fetch/JSON/AbortController/DOM events; project = Mock API with loading/success/empty/timeout/cancel/error states).
The final project and all training use vibe coding by default; assess requirements, review, debugging, tests, architecture, and product judgment rather than no-AI memorization.
The learner has a C++/Qt/multithreading/network/Python/LangChain/RAG background; teach JS async by contrast with C++ preemptive threading + locks.
The WSL project root is `\\wsl.localhost\Ubuntu\home\chr\projects\ai-knowledge-base`; the active theme is `/www/wwwroot/xiaochublog.top/wp-content/themes/colibri-wp`.
The rollback copy is `/www/backup/xiaochublog-theme-before-manual-release-/colibri-wp`; do not delete it.
Publishing requires explicit approval, no subagents, and no Git commits without explicit authorization; WPVibe OAuth is connected.
The repository is on unborn `main` with all files uncommitted; preserve existing user changes.
