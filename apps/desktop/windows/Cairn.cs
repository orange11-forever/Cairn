using System;
using System.Diagnostics;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try
        {
            Lifetime.Contain();
            Application.Run(new CairnWindow(args));
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Cairn 启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

internal sealed class CairnWindow : Form
{
    private readonly string bundle = AppDomain.CurrentDomain.BaseDirectory;
    private readonly string locationFile;
    private readonly bool customData;
    private string data;
    private Process runtime;
    private WebView2 web;
    private string origin;
    private bool closing;
    private bool stopping;
    private bool busy;
    private bool handlingDesktopCommand;
    private readonly Label status = new Label();
    private readonly Button retryStartup = new Button();
    private string modelDescription = "模型状态尚未读取。";

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    private void ApplyWindowTheme(bool dark)
    {
        int enabled = dark ? 1 : 0;
        int caption = dark ? 0x2b2017 : 0xfdfcfc;
        int foreground = dark ? 0xf5ede6 : 0x422b18;
        Marshal.ThrowExceptionForHR(DwmSetWindowAttribute(Handle, 20, ref enabled, 4));
        Marshal.ThrowExceptionForHR(DwmSetWindowAttribute(Handle, 35, ref caption, 4));
        Marshal.ThrowExceptionForHR(DwmSetWindowAttribute(Handle, 34, ref caption, 4));
        Marshal.ThrowExceptionForHR(DwmSetWindowAttribute(Handle, 36, ref foreground, 4));
    }

    public CairnWindow(string[] args)
    {
        string appHome = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Cairn", "DesktopPrototype");
        locationFile = Path.Combine(appHome, "active-data.txt");
        data = File.Exists(locationFile) ? File.ReadAllText(locationFile).Trim() : Path.Combine(appHome, "data");
        if (args.Length == 2 && args[0] == "--data") { data = Path.GetFullPath(args[1]); customData = true; }
        else if (args.Length != 0) { throw new ArgumentException("Usage: Cairn.exe [--data directory]"); }
        Text = "Cairn · 桌面样机";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Width = 1280; Height = 860; MinimumSize = new Size(760, 560);
        StartPosition = FormStartPosition.CenterScreen;
        status.Text = "正在启动 Cairn…";
        status.Dock = DockStyle.Fill;
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.Font = new Font("Microsoft YaHei UI", 12);
        Controls.Add(status);
        retryStartup.Text = "重试启动";
        retryStartup.Size = new Size(100, 36);
        retryStartup.Location = new Point(ClientSize.Width - 120, 16);
        retryStartup.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        retryStartup.Font = new Font("Microsoft YaHei UI", 9);
        retryStartup.Click += async (s, e) => {
            if (busy) return;
            busy = true; retryStartup.Enabled = false;
            try { await StopRuntime(); await StartRuntime(); }
            catch (Exception error) { ShowFailure(error); }
            finally { busy = false; retryStartup.Enabled = true; }
        };
        status.Controls.Add(retryStartup);
        Shown += async (s, e) => { FitInitialBounds(); try { await StartRuntime(); } catch (Exception error) { ShowFailure(error); } };
        FormClosing += OnClosing;
    }

    private void FitInitialBounds()
    {
        Rectangle area = Screen.FromControl(this).WorkingArea;
        MinimumSize = new Size(Math.Min(MinimumSize.Width, area.Width), Math.Min(MinimumSize.Height, area.Height));
        int width = Math.Min(Width, area.Width);
        int height = Math.Min(Height, area.Height);
        Bounds = new Rectangle(area.Left + (area.Width - width) / 2, area.Top + (area.Height - height) / 2, width, height);
    }

    internal static string DesktopAction(string expectedOrigin, string source, string message)
    {
        Uri sender;
        if (!Uri.TryCreate(source, UriKind.Absolute, out sender) ||
            sender.GetLeftPart(UriPartial.Authority) != expectedOrigin) return null;
        switch (message)
        {
            case "\"cairn:theme:dark\"": return "theme-dark";
            case "\"cairn:theme:light\"": return "theme-light";
            case "\"cairn:settings:models\"": return "models";
            case "\"cairn:settings:backup\"": return "backup";
            case "\"cairn:settings:restore\"": return "restore";
            case "\"cairn:settings:folder\"": return "folder";
            case "\"cairn:settings:diagnostics\"": return "diagnostics";
            default: return null;
        }
    }

    private void ShowDiagnostics()
    {
        MessageBox.Show(this, "本机数据目录：\n" + data + "\n\n数据库、API 和后台任务由应用管理。\n" + modelDescription + "\n配置状态不表示服务已联网或推理成功。", "帮助与诊断");
    }

    private static string Quote(string value)
    {
        var result = new System.Text.StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
            result.Append(character); slashes = 0;
        }
        result.Append('\\', slashes * 2); result.Append('"');
        return result.ToString();
    }

    private Process CreateRuntime(string command, string directory, string archive)
    {
        var start = new ProcessStartInfo(Path.Combine(bundle, "python", "python.exe"));
        start.Arguments = "-X utf8 -u -m cairn_desktop.runtime " + command + " --bundle " + Quote(bundle.TrimEnd(Path.DirectorySeparatorChar)) + " --data " + Quote(directory);
        if (archive != null) start.Arguments += " --archive " + Quote(archive);
        start.UseShellExecute = false; start.CreateNoWindow = true;
        start.RedirectStandardInput = true; start.RedirectStandardOutput = true; start.RedirectStandardError = true;
        start.StandardOutputEncoding = new System.Text.UTF8Encoding(false);
        start.StandardErrorEncoding = new System.Text.UTF8Encoding(false);
        start.WorkingDirectory = bundle;
        return new Process { StartInfo = start, EnableRaisingEvents = true };
    }

    private async Task StartRuntime()
    {
        if (runtime != null) throw new Exception("原有服务尚未退出，请先关闭窗口并查看日志。");
        busy = true;
        try
        {
        retryStartup.Enabled = false;
        status.Text = "正在启动本地服务…"; status.Visible = true;
        runtime = CreateRuntime("serve", data, null);
        string diagnostics = "";
        runtime.ErrorDataReceived += (s, e) => { if (e.Data != null) diagnostics += e.Data + "\n"; };
        Process launched = runtime;
        runtime.Exited += (s, e) => {
            if (!stopping && !closing && IsHandleCreated)
                BeginInvoke((Action)(() => { if (runtime == launched && !stopping && !closing) ShowFailure(new Exception("本地服务已退出。\n" + diagnostics)); }));
        };
        runtime.Start(); runtime.BeginErrorReadLine();
        var lineTask = runtime.StandardOutput.ReadLineAsync();
        if (await Task.WhenAny(lineTask, Task.Delay(120000)) != lineTask)
            throw new Exception("本地服务启动超时。请查看 " + Path.Combine(data, "logs", "runtime.log"));
        string line = await lineTask;
        if (line == null) throw new Exception("本地服务启动失败。\n" + diagnostics);
        var ready = new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string, object>>(line);
        origin = (string)ready["origin"];
        if (ready.ContainsKey("modelStatus")) modelDescription = DescribeModels((Dictionary<string, object>)ready["modelStatus"]);
        Uri uri = new Uri(origin);
        if (uri.Scheme != "http" || uri.Host != "127.0.0.1") throw new Exception("本地服务返回了无效地址");
        web = new WebView2 { Dock = DockStyle.Fill };
        Controls.Add(web); web.BringToFront();
        var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(data, "webview"));
        await web.EnsureCoreWebView2Async(environment);
        web.CoreWebView2.Settings.AreDevToolsEnabled = false;
        web.CoreWebView2.Settings.AreHostObjectsAllowed = false;
        web.CoreWebView2.Settings.IsWebMessageEnabled = true;
        web.CoreWebView2.WebMessageReceived += (s, e) => {
            string action = DesktopAction(origin, e.Source, e.WebMessageAsJson);
            if (action == null || closing) return;
            if (action == "theme-dark" || action == "theme-light")
            {
                try { ApplyWindowTheme(action == "theme-dark"); }
                catch (Exception error) { BeginInvoke((Action)(() => MessageBox.Show(this, error.Message, "窗口外观设置失败"))); }
                return;
            }
            if (busy || handlingDesktopCommand) return;
            handlingDesktopCommand = true;
            // Native modal dialogs must run after the WebView2 callback returns.
            BeginInvoke((Action)(async () => {
            try
            {
                if (closing) return;
                switch (action)
                {
                    case "models": await ConfigureModels(); break;
                    case "backup": await Backup(); break;
                    case "restore": await Restore(); break;
                    case "folder": Process.Start("explorer.exe", Quote(data)); break;
                    case "diagnostics": ShowDiagnostics(); break;
                }
            }
            catch (Exception error) { MessageBox.Show(this, error.Message, "设置操作失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            finally { handlingDesktopCommand = false; }
            }));
        };
        web.CoreWebView2.Settings.IsStatusBarEnabled = false;
        var cookies = web.CoreWebView2.CookieManager;
        var cookie = cookies.CreateCookie((string)ready["cookie"], (string)ready["token"], "127.0.0.1", "/");
        cookie.IsHttpOnly = true; cookie.SameSite = CoreWebView2CookieSameSiteKind.Strict;
        cookies.AddOrUpdateCookie(cookie);
        web.CoreWebView2.NavigationStarting += (s, e) => {
            Uri destination;
            if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out destination) || destination.GetLeftPart(UriPartial.Authority) != origin) e.Cancel = true;
        };
        web.CoreWebView2.NavigationCompleted += (s, e) => {
            if (!closing && !stopping &&
                ((!e.IsSuccess && e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled) || e.HttpStatusCode >= 400))
                ShowFailure(new Exception("界面加载失败，请重试启动。\n" + e.WebErrorStatus + "（HTTP " + e.HttpStatusCode + "）"));
        };
        web.CoreWebView2.NewWindowRequested += (s, e) => { e.Handled = true; };
        web.CoreWebView2.PermissionRequested += (s, e) => { e.State = CoreWebView2PermissionState.Deny; };
        web.CoreWebView2.Navigate(origin);
        status.Visible = false; retryStartup.Enabled = true;
        }
        catch (Exception startupError)
        {
            try { await StopRuntime(); }
            catch (Exception cleanupError) { throw new Exception(startupError.Message + "\n\n清理提示：" + cleanupError.Message, startupError); }
            throw;
        }
        finally { busy = false; }
    }

    private async Task StopRuntime()
    {
        stopping = true;
        try
        {
            if (web != null) { Controls.Remove(web); web.Dispose(); web = null; }
            status.Visible = true; status.Text = "正在安全关闭本地服务…";
            if (runtime != null)
            {
                if (!runtime.HasExited)
                {
                    await runtime.StandardInput.WriteLineAsync("stop");
                    await runtime.StandardInput.FlushAsync();
                    bool exited = await Task.Run(() => runtime.WaitForExit(90000));
                    if (!exited) { runtime.Kill(); throw new Exception("服务未能按时关闭；下次启动将执行数据库恢复。请查看日志。"); }
                }
                int code = runtime.ExitCode;
                runtime.Dispose(); runtime = null;
                if (code != 0) throw new Exception("本地服务关闭时发生错误。请查看 " + Path.Combine(data, "logs", "runtime.log"));
            }
        }
        finally { stopping = false; }
    }

    private async Task RunDataCommand(string command, string directory, string archive)
    {
        using (Process process = CreateRuntime(command, directory, archive))
        {
            process.Start();
            Task<string> errors = process.StandardError.ReadToEndAsync();
            Task<string> output = process.StandardOutput.ReadToEndAsync();
            await Task.Run(() => process.WaitForExit());
            string error = await errors; await output;
            if (process.ExitCode != 0) throw new Exception("数据操作失败。\n" + error);
        }
    }

    private async Task Backup()
    {
        if (busy) return;
        using (var dialog = new SaveFileDialog { Filter = "Cairn 备份|*.cairn", FileName = "Cairn-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".cairn" })
        {
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            if (File.Exists(dialog.FileName)) { MessageBox.Show("请选择新的文件名，已有备份会保留。"); return; }
            busy = true; retryStartup.Enabled = false;
            try
            {
                await StopRuntime();
                status.Text = "正在备份本地数据…";
                await RunDataCommand("backup", data, dialog.FileName);
                MessageBox.Show("备份已保存。文件包含账号和项目数据，请妥善保管。模型凭据不在备份内；恢复后需重新填写。", "Cairn");
            }
            catch (Exception error) { MessageBox.Show(error.Message, "备份失败"); }
            finally { busy = false; try { await StartRuntime(); } catch (Exception error) { ShowFailure(error); } }
        }
    }

    private async Task Restore()
    {
        if (busy) return;
        using (var archive = new OpenFileDialog { Filter = "Cairn 备份|*.cairn", Title = "选择你信任的 Cairn 备份" })
        using (var folder = new FolderBrowserDialog { Description = "选择恢复位置；应用会创建新目录，保留当前数据。" })
        {
            if (archive.ShowDialog(this) != DialogResult.OK || folder.ShowDialog(this) != DialogResult.OK) return;
            string destination = Path.Combine(folder.SelectedPath, "Cairn-restored-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
            busy = true; retryStartup.Enabled = false;
            try
            {
                await StopRuntime(); status.Text = "正在校验并恢复备份…";
                await RunDataCommand("restore", destination, archive.FileName);
                data = destination;
                if (!customData) File.WriteAllText(locationFile, data);
            }
            catch (Exception error) { MessageBox.Show(error.Message, "恢复失败"); }
            finally { busy = false; try { await StartRuntime(); } catch (Exception error) { ShowFailure(error); } }
        }
    }

    private static string DescribeModels(Dictionary<string, object> value)
    {
        if ((bool)value["corrupt"]) return "模型配置损坏，请打开AI模型设置明确清除或重新配置。";
        int count = 0; foreach (object item in (System.Collections.IEnumerable)value["answerModels"]) count++;
        string answer = count == 0 ? "未配置" : count + "个已保存（状态不代表调用成功）";
        string embedding = value["embedding"] == null ? "未配置，索引任务已暂停；文件解包仍可用" : "已配置，1024维（未经联网验证）";
        return "回答模型：" + answer + "\n知识索引：" + embedding;
    }

    private async Task<Dictionary<string, object>> RunModelCommand(string command, Dictionary<string, object> payload)
    {
        using (Process process = CreateRuntime(command, data, null))
        {
            process.Start();
            Task<string> errors = process.StandardError.ReadToEndAsync();
            Task<string> output = process.StandardOutput.ReadToEndAsync();
            using (var input = new StreamWriter(process.StandardInput.BaseStream, new System.Text.UTF8Encoding(false)))
            {
                if (payload != null) await input.WriteAsync(new JavaScriptSerializer().Serialize(payload));
                await input.FlushAsync();
            }
            await Task.Run(() => process.WaitForExit());
            string error = await errors;
            string response = await output;
            if (process.ExitCode != 0) throw new Exception("模型设置操作失败。\n" + error);
            return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(response);
        }
    }

    private async Task ConfigureModels()
    {
        if (busy) return;
        bool restart = runtime != null && !runtime.HasExited;
        string previousStatus = status.Text;
        bool changed = false;
        busy = true; retryStartup.Enabled = false;
        try
        {
            bool previouslyExited = runtime != null && runtime.HasExited;
            try { await StopRuntime(); }
            catch (Exception stopError) { if (!previouslyExited) throw; previousStatus += "\n" + stopError.Message; }
            var existing = await RunModelCommand("model-status", null);
            modelDescription = DescribeModels(existing);
            using (var dialog = new ModelConfigurationDialog(existing, payload => RunModelCommand("model-test", payload)))
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                status.Text = "正在校验并加密保存模型设置…";
                var saved = await RunModelCommand("model-configure", dialog.Payload);
                changed = true;
                modelDescription = DescribeModels(saved);
            }
        }
        catch (Exception error) { MessageBox.Show(error.Message, "模型设置失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        finally
        {
            busy = false;
            if (changed || restart)
            {
                try { await StartRuntime(); }
                catch (Exception error) { ShowFailure(error); }
            }
            else { status.Text = previousStatus; status.Visible = true; retryStartup.Enabled = true; retryStartup.BringToFront(); }
        }
    }

    private void ShowFailure(Exception error)
    {
        if (web != null) web.Visible = false;
        status.Visible = true;
        status.Text = "Cairn 未能继续运行\n\n" + error.Message;
        status.BringToFront();
        retryStartup.Enabled = true;
        retryStartup.BringToFront();
    }

    private async void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (closing) return;
        e.Cancel = true;
        if (busy) { MessageBox.Show("请等待当前数据操作完成。"); return; }
        closing = true; retryStartup.Enabled = false;
        try { await StopRuntime(); }
        catch (Exception error) { MessageBox.Show(error.Message, "Cairn 关闭提示"); }
        Close();
    }
}

internal sealed class ModelConfigurationDialog : Form
{
    public Dictionary<string, object> Payload { get; private set; }
    private readonly ModelCatalogEditor answers;
    private readonly ModelConnectionEditor embedding;
    private bool testing;

    public ModelConfigurationDialog(Dictionary<string, object> existing, Func<Dictionary<string, object>, Task<Dictionary<string, object>>> probe)
    {
        Text = "Cairn AI 模型设置"; AccessibleName = "AI 模型设置对话框";
        Width = 900; Height = 760; MinimumSize = new Size(760, 680);
        StartPosition = FormStartPosition.CenterParent; MinimizeBox = false; MaximizeBox = false;
        Font = new Font("Microsoft YaHei UI", 9);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Padding = new Padding(16) };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        for (int i = 0; i < 3; i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        bool corrupt = (bool)existing["corrupt"];
        layout.Controls.Add(new Label { AutoSize = true, MaximumSize = new Size(820, 0), Text = corrupt ? "配置损坏，请先明确清除全部模型配置，再重新填写；项目数据会保留。" : "管理回答模型，随后在项目的助手配置中分别选用。知识索引独立配置。保存会重启本地服务。" }, 0, 0);
        var tabs = new TabControl { Dock = DockStyle.Fill, AccessibleName = "模型用途", TabIndex = 0 };
        var answerTab = new TabPage("回答模型"); var indexTab = new TabPage("知识索引（1024维）");
        answers = new ModelCatalogEditor((System.Collections.IEnumerable)existing["answerModels"], existing["defaultModelId"] as string);
        embedding = new ModelConnectionEditor("知识索引", existing["embedding"] as Dictionary<string, object>, true);
        answerTab.Controls.Add(answers); indexTab.Controls.Add(embedding); tabs.TabPages.Add(answerTab); tabs.TabPages.Add(indexTab);
        layout.Controls.Add(tabs, 0, 1);
        layout.Controls.Add(new Label { AutoSize = true, MaximumSize = new Size(820, 0), Text = "Key 留空保留该模型已保存的凭据；新增模型必须填写。无鉴权本地服务可填 local-no-auth。\n已有索引只允许更换 Key；模型凭据不进入备份。测试会向所填服务发送一次小请求，可能消耗少量额度。" }, 0, 2);
        var result = new Label { AutoSize = true, MaximumSize = new Size(820, 0), AccessibleName = "模型测试结果", Text = "配置已读取。尚未测试；保存不代表服务连通或调用成功。", Margin = new Padding(0, 12, 0, 12) };
        layout.Controls.Add(result, 0, 3);
        Action resetTest = () => result.Text = "配置有未保存修改。请测试当前配置；先前测试结果已失效。";
        answers.Changed += resetTest; embedding.Changed += resetTest;
        var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, TabIndex = 1 };
        var save = new Button { Text = "保存并重启", AutoSize = true, AccessibleName = "保存模型设置并重启", Enabled = !corrupt };
        var cancel = new Button { Text = "取消", AutoSize = true, AccessibleName = "取消模型设置", DialogResult = DialogResult.Cancel };
        var test = new Button { Text = "测试所选模型", AutoSize = true, AccessibleName = "测试所选模型", Enabled = !corrupt };
        var clear = new Button { Text = "清除全部配置…", AutoSize = true, AccessibleName = "清除全部模型配置" };
        save.Click += (s, e) => {
            try { Payload = Configuration(); DialogResult = DialogResult.OK; }
            catch (Exception error) { MessageBox.Show(this, error.Message, "请检查模型设置"); }
        };
        test.Click += async (s, e) => {
            try {
                var payload = new Dictionary<string, object> { { "configuration", Configuration() }, { "kind", tabs.SelectedIndex == 0 ? "answer" : "embedding" }, { "modelId", answers.SelectedId } };
                testing = true; tabs.Enabled = buttons.Enabled = false;
                result.Text = "正在测试服务连通和实际调用…";
                var response = await probe(payload);
                result.Text = (string)response["message"];
            }
            catch (Exception error) { result.Text = "测试未完成：" + error.Message; }
            finally { testing = false; tabs.Enabled = buttons.Enabled = true; }
        };
        clear.Click += (s, e) => {
            if (MessageBox.Show(this, "清除所有模型凭据？项目、文件与已有索引会保留；索引任务将暂停。", "确认清除模型配置", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            Payload = new Dictionary<string, object> { { "clearAll", true } }; DialogResult = DialogResult.OK;
        };
        FormClosing += (s, e) => { if (testing) e.Cancel = true; };
        buttons.Controls.Add(save); buttons.Controls.Add(cancel); buttons.Controls.Add(test); buttons.Controls.Add(clear); layout.Controls.Add(buttons, 0, 4);
        Controls.Add(layout); AcceptButton = save; CancelButton = cancel;
    }
    private Dictionary<string, object> Configuration()
    {
        return new Dictionary<string, object> { { "answerModels", answers.Value() }, { "defaultModelId", answers.DefaultId }, { "embedding", embedding.Value() } };
    }
}

internal sealed class ModelCatalogEditor : UserControl
{
    private readonly ListBox list = new ListBox();
    private readonly Panel detail = new Panel();
    private readonly List<ModelConnectionEditor> editors = new List<ModelConnectionEditor>();
    private readonly Label empty = new Label { Text = "尚无回答模型。点击“添加模型”后填写连接信息。", AutoSize = true, Dock = DockStyle.Top };
    public string DefaultId { get; private set; }
    public string SelectedId { get { return list.SelectedIndex < 0 ? null : editors[list.SelectedIndex].ModelId; } }
    public event Action Changed;

    public ModelCatalogEditor(System.Collections.IEnumerable existing, string defaultId)
    {
        Dock = DockStyle.Fill; DefaultId = defaultId; Padding = new Padding(8);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 205)); layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        list.Dock = DockStyle.Fill; list.AccessibleName = "回答模型列表"; list.IntegralHeight = false; list.HorizontalScrollbar = true;
        detail.Dock = DockStyle.Fill; detail.Controls.Add(empty);
        list.SelectedIndexChanged += (s, e) => ShowSelected();
        layout.Controls.Add(list, 0, 0); layout.Controls.Add(detail, 1, 0); layout.SetRowSpan(detail, 2);
        var actions = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill };
        var add = new Button { Text = "添加模型", AutoSize = true, AccessibleName = "添加回答模型" };
        var remove = new Button { Text = "删除模型", AutoSize = true, AccessibleName = "删除所选模型" };
        var makeDefault = new Button { Text = "设为默认", AutoSize = true, AccessibleName = "设为默认模型" };
        add.Click += (s, e) => {
            if (editors.Count >= 20) { MessageBox.Show(this, "最多保存20个回答模型。"); return; }
            Add(null); list.SelectedIndex = editors.Count - 1; Notify();
        };
        remove.Click += (s, e) => {
            int index = list.SelectedIndex; if (index < 0) return;
            if (MessageBox.Show(this, "保存后将删除该模型及凭据；选用它的助手需重新选择模型。历史回答会保留。", "删除模型", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            var editor = editors[index]; editors.RemoveAt(index); list.Items.RemoveAt(index); detail.Controls.Remove(editor); editor.Dispose();
            if (DefaultId == editor.ModelId) DefaultId = editors.Count == 0 ? null : editors[0].ModelId;
            RefreshNames(); list.SelectedIndex = editors.Count == 0 ? -1 : Math.Min(index, editors.Count - 1); ShowSelected(); Notify();
        };
        makeDefault.Click += (s, e) => { if (SelectedId != null) { DefaultId = SelectedId; RefreshNames(); Notify(); } };
        actions.Controls.Add(add); actions.Controls.Add(remove); actions.Controls.Add(makeDefault); layout.Controls.Add(actions, 0, 1);
        Controls.Add(layout);
        foreach (Dictionary<string, object> item in existing) Add(item);
        if (editors.Count > 0) list.SelectedIndex = 0;
    }
    private void Notify() { if (Changed != null) Changed(); }
    private void Add(Dictionary<string, object> value)
    {
        var editor = new ModelConnectionEditor("回答模型", value, false);
        editors.Add(editor); editor.Visible = false; detail.Controls.Add(editor);
        if (DefaultId == null) DefaultId = editor.ModelId;
        list.Items.Add(""); RefreshNames();
        editor.Changed += () => { RefreshNames(); Notify(); };
    }
    private void RefreshNames()
    {
        for (int i = 0; i < editors.Count; i++) list.Items[i] = editors[i].DisplayName + (editors[i].ModelId == DefaultId ? "（默认）" : "");
    }
    private void ShowSelected()
    {
        empty.Visible = editors.Count == 0;
        for (int i = 0; i < editors.Count; i++) editors[i].Visible = i == list.SelectedIndex;
    }
    public object[] Value()
    {
        var result = new List<object>(); foreach (var editor in editors) result.Add(editor.Value()); return result.ToArray();
    }
}

internal sealed class ModelConnectionEditor : UserControl
{
    private readonly string purpose;
    private readonly bool index;
    private readonly bool hasKey;
    private readonly CheckBox enabled = new CheckBox();
    private readonly ComboBox protocol = new ComboBox();
    private readonly TextBox displayName = new TextBox();
    private readonly TextBox address = new TextBox();
    private readonly TextBox model = new TextBox();
    private readonly TextBox key = new TextBox();
    public string ModelId { get; private set; }
    public string DisplayName { get { return String.IsNullOrWhiteSpace(displayName.Text) ? "新模型" : displayName.Text; } }
    public event Action Changed;

    public ModelConnectionEditor(string purpose, Dictionary<string, object> existing, bool index)
    {
        this.purpose = purpose; this.index = index; hasKey = existing != null && (bool)existing["hasKey"];
        ModelId = index ? null : existing != null ? (string)existing["id"] : "model-" + Guid.NewGuid().ToString("N");
        Dock = DockStyle.Fill; AutoScroll = true; Padding = new Padding(12);
        var layout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        enabled.Text = "启用" + purpose; enabled.AccessibleName = enabled.Text; enabled.AutoSize = true; enabled.TabIndex = 0; enabled.Checked = !index || existing != null;
        if (index) layout.Controls.Add(enabled);
        else { AddField(layout, "显示名称", displayName, purpose + "显示名称", 0); displayName.MaxLength = 80; displayName.Text = existing != null ? (string)existing["name"] : "新模型"; }
        protocol.DropDownStyle = ComboBoxStyle.DropDownList; protocol.Dock = DockStyle.Top; protocol.AccessibleName = purpose + "协议"; protocol.TabIndex = 1;
        protocol.Items.AddRange(index ? new object[] { "openai-compatible" } : new object[] { "openai-compatible", "openai-responses", "anthropic", "gemini" });
        protocol.SelectedItem = existing != null ? (string)existing["protocol"] : "openai-compatible";
        layout.Controls.Add(new Label { Text = "协议", AutoSize = true }); layout.Controls.Add(protocol);
        AddField(layout, "服务基础地址（例如 http://localhost:11434/v1）", address, purpose + "服务基础地址", 2);
        AddField(layout, "模型名称", model, purpose + "模型名称", 3);
        AddField(layout, hasKey ? "API Key（已保存，留空保留）" : "API Key（未保存）", key, purpose + "API Key", 4);
        address.MaxLength = 16000; model.MaxLength = 200; key.MaxLength = 4096; key.UseSystemPasswordChar = true;
        if (existing != null) { address.Text = (string)existing["baseUrl"]; model.Text = (string)existing["model"]; }
        enabled.CheckedChanged += (s, e) => { SetFieldsEnabled(); Notify(); };
        foreach (var field in new [] { displayName, address, model, key }) field.TextChanged += (s, e) => Notify();
        protocol.SelectedIndexChanged += (s, e) => Notify();
        SetFieldsEnabled(); Controls.Add(layout);
    }
    private void Notify() { if (Changed != null) Changed(); }
    private static void AddField(TableLayoutPanel layout, string label, TextBox input, string accessibleName, int tabIndex)
    {
        layout.Controls.Add(new Label { Text = label, AutoSize = true, Margin = new Padding(0, 12, 0, 4) });
        input.Dock = DockStyle.Top; input.AccessibleName = accessibleName; input.TabIndex = tabIndex; layout.Controls.Add(input);
    }
    private void SetFieldsEnabled() { protocol.Enabled = address.Enabled = model.Enabled = key.Enabled = enabled.Checked; }
    public object Value()
    {
        if (!enabled.Checked) return null;
        if (!index && String.IsNullOrWhiteSpace(displayName.Text)) throw new Exception("请填写模型显示名称。");
        if (String.IsNullOrWhiteSpace(address.Text) || String.IsNullOrWhiteSpace(model.Text)) throw new Exception(DisplayName + "需要填写服务地址和模型名称。");
        if (!hasKey && String.IsNullOrWhiteSpace(key.Text)) throw new Exception(DisplayName + "需要 API Key；无鉴权本地服务可明确填写 local-no-auth。");
        var value = new Dictionary<string, object> { { "protocol", (string)protocol.SelectedItem }, { "baseUrl", address.Text }, { "model", model.Text }, { "apiKey", key.Text } };
        if (index) value.Add("dimensions", 1024);
        else { value.Add("id", ModelId); value.Add("name", displayName.Text); }
        return value;
    }
}

internal static class Lifetime
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Limits { public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinSet, MaxSet; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
    [StructLayout(LayoutKind.Sequential)]
    private struct Io { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct Extended { public Limits Basic; public Io Io; public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(IntPtr job, int kind, ref Extended info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    private static IntPtr job;
    private static System.Threading.Mutex running;
    public static void Contain()
    {
        // Atomically publish the running signal against install/uninstall startup.
        bool created;
        using (var maintenance = new System.Threading.Mutex(true, @"Local\Cairn.Desktop.Maintenance.v1", out created))
        {
            if (!created) throw new InvalidOperationException("Cairn安装或卸载正在进行，请完成后再启动。");
            // Existence is an install/uninstall signal, not an exclusive data lock.
            running = new System.Threading.Mutex(false, @"Local\Cairn.Desktop.Running.v1");
            maintenance.ReleaseMutex();
        }
        job = CreateJobObject(IntPtr.Zero, null);
        var info = new Extended(); info.Basic.Flags = 0x2000;
        if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref info, (uint)Marshal.SizeOf(info)) || !AssignProcessToJobObject(job, Process.GetCurrentProcess().Handle))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    }
}
