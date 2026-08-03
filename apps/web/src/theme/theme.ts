export const THEME_STORAGE_KEY = "cairn-theme";
export const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export function readThemePreference(storage: Pick<Storage, "getItem">): ThemePreference {
  try {
    const value = storage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function writeThemePreference(
  preference: ThemePreference,
  storage: Pick<Storage, "setItem" | "removeItem">,
): void {
  try {
    if (preference === "system") storage.removeItem(THEME_STORAGE_KEY);
    else storage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    return;
  }
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}
