import { Monitor, Moon, Sun } from "lucide-react";

import { useTheme } from "../theme/ThemeContext.tsx";
import type { ThemePreference } from "../theme/theme.ts";

const OPTIONS: readonly {
  value: ThemePreference;
  label: string;
  icon: typeof Monitor;
}[] = [
  { value: "system", label: "跟随系统", icon: Monitor },
  { value: "light", label: "日间", icon: Sun },
  { value: "dark", label: "夜间", icon: Moon },
];

export function ThemeControl() {
  const { preference, setPreference } = useTheme();

  return (
    <fieldset className="theme-control">
      <legend>外观</legend>
      {OPTIONS.map((option) => {
        const Icon = option.icon;
        return (
          <label key={option.value}>
            <input
              type="radio"
              name="theme-preference"
              value={option.value}
              checked={preference === option.value}
              onChange={() => setPreference(option.value)}
            />
            <span>
              <Icon aria-hidden="true" size={16} strokeWidth={1.8} />
              {option.label}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
