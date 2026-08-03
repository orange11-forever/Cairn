import { createContext, useContext, useEffect, useLayoutEffect, useState } from "react";

import {
  DARK_SCHEME_QUERY,
  readThemePreference,
  resolveTheme,
  writeThemePreference,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme.ts";

interface ThemeContextValue {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference(preference: ThemePreference): void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    readThemePreference(window.localStorage),
  );
  const [systemDark, setSystemDark] = useState(() => window.matchMedia(DARK_SCHEME_QUERY).matches);
  const resolvedTheme = resolveTheme(preference, systemDark);

  useEffect(() => {
    const media = window.matchMedia(DARK_SCHEME_QUERY);
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    setSystemDark(media.matches);
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
  }, [resolvedTheme]);

  function setPreference(next: ThemePreference): void {
    writeThemePreference(next, window.localStorage);
    setPreferenceState(next);
  }

  return (
    <ThemeContext.Provider value={{ preference, resolvedTheme, setPreference }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === undefined) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return value;
}
