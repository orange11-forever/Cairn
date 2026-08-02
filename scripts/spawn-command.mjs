const WINDOWS_BATCH = /\.(?:cmd|bat)$/i;

export function spawnInvocation(
  command,
  args,
  { platform = process.platform, env = process.env } = {},
) {
  if (platform === "win32" && WINDOWS_BATCH.test(command)) {
    return {
      command: env.ComSpec ?? env.COMSPEC ?? "cmd.exe",
      args: ["/d", "/s", "/c", command, ...args],
    };
  }
  return { command, args };
}
