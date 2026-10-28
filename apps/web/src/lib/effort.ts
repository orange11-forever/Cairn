export function hoursToMinutes(value: string): number | null {
  if (value.trim() === "") return null;
  const hours = Number(value);
  const minutes = Math.round(hours * 60);
  if (!Number.isFinite(hours) || hours < 0 || !Number.isSafeInteger(minutes) || minutes > 2_147_483_647) throw new Error("工时必须为非负数，且换算后不超过2147483647分钟。");
  return minutes;
}
export function minutesToHours(value: number | null | undefined): string { return value === null || value === undefined ? "" : String(value / 60); }
export function effortLabel(value: number | null | undefined): string { return value === null || value === undefined ? "未填写" : `${new Intl.NumberFormat("zh-CN", {maximumFractionDigits:2}).format(value / 60)} 小时（${value} 分钟）`; }
