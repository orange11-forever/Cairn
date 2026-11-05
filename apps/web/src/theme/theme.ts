export const THEME_STORAGE_KEY = "cairn-theme";
export const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export function readThemePreference(storage: Pick<Storage, "getItem">): ThemePreference {
  try {
    const value = storage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "dark";
  } catch {
    return "dark";
  }
}

export function writeThemePreference(
  preference: ThemePreference,
  storage: Pick<Storage, "setItem">,
): void {
  try {
    storage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    return;
  }
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}
