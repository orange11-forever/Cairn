import { writeFile } from "node:fs/promises";
import { join } from "node:path";
const sourceDiagnostics = new WeakMap();

export async function installSourceFormDiagnostics(page, redactions = []) {
  const observations = { consoleErrors: [], network: [], redactions };
  sourceDiagnostics.set(page, observations);
  page.on("console", message => {
    if (message.type() === "error") observations.consoleErrors.push(message.text());
  });
  page.on("pageerror", error => observations.consoleErrors.push(error.message));
  page.on("response", response => {
    const pathname = new URL(response.url()).pathname;
    const route = pathname === "/api/v1/session" ? "session-restore" :
      pathname.endsWith("/knowledge/sources/feishu") ? "source-create" :
      pathname.endsWith("/knowledge/sources") ? "source-list" :
      /^\/api\/v1\/projects\/[^/]+$/.test(pathname) ? "project-read" : null;
    if (route) observations.network.push({ route, method: response.request().method(), status: response.status() });
  });
  await page.evaluate(() => {
    const events = { submit: 0, submitPrevented: 0, submitClick: 0, invalid: 0 };
    window.__cairnSourceFormEvents = events;
    document.addEventListener("submit", event => {
      if (!(event.target instanceof HTMLFormElement) || !event.target.closest(".feishu-source-form-region")) return;
      events.submit += 1;
      queueMicrotask(() => { if (event.defaultPrevented) events.submitPrevented += 1; });
    }, true);
    document.addEventListener("click", event => {
      if (event.target instanceof Element && event.target.closest('.feishu-source-form-region button[type="submit"]')) events.submitClick += 1;
    }, true);
    document.addEventListener("invalid", event => {
      if (event.target instanceof Element && event.target.closest(".feishu-source-form-region")) events.invalid += 1;
    }, true);
  });
}

export async function waitForSourceResponse({ page, label, predicate, action, screenshotDir }) {
  let failurePhase = null;
  try {
    const [response] = await Promise.all([
      page.waitForResponse(predicate).catch(error => { failurePhase ??= "response"; throw error; }),
      action().catch(error => { failurePhase ??= "action"; throw error; }),
    ]);
    return response;
  } catch {
    const observations = sourceDiagnostics.get(page) ?? { consoleErrors: [], network: [], redactions: [] };
    const snapshot = await page.evaluate(({ consoleErrors, redactions }) => {
      const region = document.querySelector(".feishu-source-form-region");
      const form = region?.querySelector("form");
      const controls = Array.from(region?.querySelectorAll("input,select") ?? []);
      const values = [...redactions, ...controls.map(control => control.value)].filter(Boolean);
      const sanitize = message => {
        let text = message ?? "";
        for (const value of values) text = text.replaceAll(value, "[redacted]");
        return text.replace(/https?:\/\/\S+/g, "[url]")
          .replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[email]")
          .replace(/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/gi, "[id]");
      };
      const submit = form?.querySelector('button[type="submit"]');
      return {
        visible: document.visibilityState === "visible", online: navigator.onLine,
        pageKind: location.pathname.endsWith("/knowledge/sources") ? "sources" : location.pathname === "/login" ? "login" : "other",
        authenticatedShell: document.querySelector(".account-menu") !== null,
        events: window.__cairnSourceFormEvents ?? null,
        formPresent: form !== undefined && form !== null, noValidate: form?.noValidate ?? null,
        submitDisabled: submit?.disabled ?? null,
        saving: submit?.textContent?.trim() === "正在保存…",
        controls: controls.map((control, index) => ({ index, type: control.type,
          empty: control.value === "", disabled: control.disabled, required: control.required, ariaInvalid: control.getAttribute("aria-invalid"),
          checked: control.type === "checkbox" ? control.checked : undefined,
          validity: { valid: control.validity.valid, valueMissing: control.validity.valueMissing,
            typeMismatch: control.validity.typeMismatch, patternMismatch: control.validity.patternMismatch,
            tooLong: control.validity.tooLong, tooShort: control.validity.tooShort, customError: control.validity.customError } })),
        errors: Array.from(document.querySelectorAll(".feishu-source-form-region [role='alert'],.feishu-access-message [role='alert']"))
          .map(node => sanitize(node.textContent)),
        consoleErrors: consoleErrors.map(sanitize),
      };
    }, { consoleErrors: observations.consoleErrors, redactions: observations.redactions });
    snapshot.network = observations.network;
    await writeFile(join(screenshotDir, `${label}-diagnostic.json`), JSON.stringify({ responseWait: label, failurePhase, ...snapshot }, null, 2), { mode: 0o600 });
    const screenshot = label === "feishu-create" ? "feishu-create-failure.png" : `${label}-failure.png`;
    await page.screenshot({ path: join(screenshotDir, screenshot), fullPage: true,
      mask: [page.locator("input,select,.account-menu,.workspace-header p,.feishu-source-list strong,.feishu-detail-heading p,.feishu-facts dd")] });
    console.error(`[source-diagnostic] ${JSON.stringify({ responseWait: label, failurePhase, ...snapshot })}`);
    throw new Error(`Source action/response failed: ${label} (${failurePhase}); sanitized diagnostic and masked screenshot captured`);
  }
}
