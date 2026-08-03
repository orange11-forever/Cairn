import { useTheme } from "../theme/ThemeContext.tsx";
import type { ThemePreference } from "../theme/theme.ts";

const OPTIONS: readonly { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "日间" },
  { value: "dark", label: "夜间" },
];

export function ThemeControl() {
  const { preference, setPreference } = useTheme();

  return (
    <fieldset className="theme-control">
      <legend>外观</legend>
      {OPTIONS.map((option) => (
        <label key={option.value}>
          <input
            type="radio"
            name="theme-preference"
            value={option.value}
            checked={preference === option.value}
            onChange={() => setPreference(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
