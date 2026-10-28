using System;

internal static class DesktopCommandTests
{
    private static void Main()
    {
        string origin = "http://127.0.0.1:58888";
        foreach (string action in new [] { "models", "backup", "restore", "folder", "diagnostics" })
            Assert(CairnWindow.DesktopAction(origin, origin + "/login", "\"cairn:settings:" + action + "\"") == action);
        foreach (string theme in new [] { "dark", "light" })
            Assert(CairnWindow.DesktopAction(origin, origin, "\"cairn:theme:" + theme + "\"") == "theme-" + theme);
        foreach (string source in new [] { "https://evil.example", "http://127.0.0.1:58889", "http://localhost:58888", "file:///page.html", "invalid" })
            Assert(CairnWindow.DesktopAction(origin, source, "\"cairn:settings:backup\"") == null);
        foreach (string message in new [] { "{}", "null", "[]", "\"cairn:settings:delete\"", "\"cairn:settings:backup C:\\\\Users\"" })
            Assert(CairnWindow.DesktopAction(origin, origin, message) == null);
        Console.WriteLine("PASS: only fixed desktop commands from the exact local origin are accepted");
    }
    private static void Assert(bool value) { if (!value) throw new Exception("Desktop command boundary failed"); }
}
