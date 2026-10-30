using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class ModelConfigurationTests
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        var first = Profile("default", "原有模型");
        var second = Profile("review", "复核模型");
        var existing = new Dictionary<string, object> { { "corrupt", false }, { "answerModels", new object[] { first, second } }, { "defaultModelId", "default" }, { "embedding", null } };
        Dictionary<string, object> probed = null;
        using (var dialog = new ModelConfigurationDialog(existing, value => { probed = value; return Task.FromResult(new Dictionary<string, object> { { "message", "服务连通，实际调用成功；配置尚未保存。" } }); }))
        {
            dialog.Show(); Application.DoEvents();
            var list = Find<ListBox>(dialog, "回答模型列表");
            Assert(list.Items.Count == 2, "two models shown");
            list.SelectedIndex = 1; Application.DoEvents();
            Assert(Find<TextBox>(dialog, "回答模型显示名称").Text == "复核模型", "selected model shown");
            Find<TextBox>(dialog, "回答模型显示名称").Text = "审查模型";
            Find<Button>(dialog, "设为默认模型").PerformClick();
            Find<Button>(dialog, "测试所选模型").PerformClick(); Application.DoEvents();
            Assert(probed != null && (string)probed["modelId"] == "review", "test targets selected model");
            Assert(Find<Label>(dialog, "模型测试结果").Text.Contains("实际调用成功"), "test result is visible");
            Find<TextBox>(dialog, "回答模型模型名称").Text = "revised-model";
            Assert(Find<Label>(dialog, "模型测试结果").Text.Contains("已失效"), "edit invalidates test result");
            Find<Button>(dialog, "添加回答模型").PerformClick(); Application.DoEvents();
            Assert(list.Items.Count == 3, "add model");
            Find<TextBox>(dialog, "回答模型显示名称").Text = "新增模型";
            Find<TextBox>(dialog, "回答模型服务基础地址").Text = "http://127.0.0.1:11434/v1";
            Find<TextBox>(dialog, "回答模型模型名称").Text = "third-model";
            Find<TextBox>(dialog, "回答模型API Key").Text = "synthetic-ui-test-key";
            if (args.Length > 0) { using (var bitmap = new Bitmap(dialog.Width, dialog.Height)) { dialog.DrawToBitmap(bitmap, new Rectangle(0, 0, dialog.Width, dialog.Height)); bitmap.Save(args[0]); } }
            Find<Button>(dialog, "保存模型设置并重启").PerformClick();
            Assert(dialog.DialogResult == DialogResult.OK, "save accepted");
            Assert((string)dialog.Payload["defaultModelId"] == "review", "default stable after add");
            var entries = (object[])dialog.Payload["answerModels"];
            Assert(entries.Length == 3, "three model payload");
            Assert((string)((Dictionary<string, object>)entries[0])["id"] == "default", "legacy ID retained");
            Assert((string)((Dictionary<string, object>)entries[1])["name"] == "审查模型", "name saved independently");
            Assert((string)((Dictionary<string, object>)entries[0])["apiKey"] == "", "no key exposed on read");
        }
        Console.WriteLine("PASS: native model catalog add/edit/default selection, probe, stale result, and credential-free readback");
    }
    private static Dictionary<string, object> Profile(string id, string name)
    {
        return new Dictionary<string, object> { { "id", id }, { "name", name }, { "protocol", "openai-compatible" }, { "baseUrl", "http://127.0.0.1:11434/v1" }, { "model", id + "-model" }, { "hasKey", true } };
    }
    private static T Find<T>(Control root, string name) where T : Control
    {
        foreach (Control child in root.Controls)
        {
            if (child is T && child.AccessibleName == name && child.Visible) return (T)child;
            T found = Find<T>(child, name); if (found != null) return found;
        }
        return null;
    }
    private static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
}
