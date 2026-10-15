using System;
using System.Threading;
using UnityEngine;

namespace GrassCraft
{
    public sealed class ModelPreviewUI : MonoBehaviour
    {
        public ModelLoader loader;
        public ModelViewerController viewer;
        public ReconstructionApiClient api;
        string modelUrl = "", taskId = "", taskStatus = "", taskError = "";
        bool following;
        CancellationTokenSource polling;
        GUIStyle title, label, hint;
        Font chineseFont;
        GUISkin chineseSkin;
        int lastWidth, lastHeight;
        public Rect Panel { get; private set; }

        void Update()
        {
            if (Screen.width == lastWidth && Screen.height == lastHeight) return;
            lastWidth = Screen.width; lastHeight = Screen.height;
            bool wide = Screen.width > Screen.height;
            float scale = Mathf.Max(.6f, Mathf.Min(Screen.width / 960f, Screen.height / 640f));
            Panel = wide ? new Rect(0,0,350*scale,Screen.height) : new Rect(0,0,Screen.width,440*scale);
            viewer.blockedScreenRect = new Rect(Panel.x, Screen.height - Panel.yMax, Panel.width, Panel.height);
            viewer.viewCamera.rect = wide ? new Rect(Panel.width/Screen.width,0,1-Panel.width/Screen.width,1)
                : new Rect(0,0,1,1-Panel.height/Screen.height);
            viewer.Refit();
        }

        void OnGUI()
        {
            float scale = Mathf.Max(.6f, Mathf.Min(Screen.width / 960f, Screen.height / 640f));
            var old = GUI.matrix;
            GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, Vector3.one*scale);
            if (title == null)
            {
                // Use installed CJK fonts without redistributing proprietary operating-system fonts.
                chineseFont = Font.CreateDynamicFontFromOSFont(new[] {
                    "Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "PingFang SC",
                    "Noto Sans CJK SC", "Noto Sans SC", "Droid Sans Fallback", "Arial Unicode MS"
                }, 16);
                chineseSkin = Instantiate(GUI.skin);
                if (chineseFont != null)
                {
                    chineseSkin.font = chineseFont;
                    foreach (var style in new[] { chineseSkin.label, chineseSkin.button, chineseSkin.textField,
                        chineseSkin.toggle, chineseSkin.box }) style.font = chineseFont;
                }
                title = new GUIStyle(chineseSkin.label) { fontSize = 25, fontStyle = FontStyle.Bold };
                label = new GUIStyle(chineseSkin.label) { fontSize = 15, wordWrap = true };
                hint = new GUIStyle(label) { fontSize = 13 };
            }
            var previousSkin = GUI.skin;
            GUI.skin = chineseSkin;
            GUI.Box(new Rect(0,0,Panel.width/scale,Panel.height/scale), "");
            GUILayout.BeginArea(new Rect(18,15,Panel.width/scale-36,Panel.height/scale-25));
            GUILayout.Label("草编工艺品 · 三维预览", title);
            GUILayout.Label("模型加载与接口联调测试", hint);
            GUILayout.Space(10);
            GUILayout.Label("后端服务地址", label);
            GUI.enabled = !following;
            api.baseUrl = GUILayout.TextField(api.baseUrl, GUILayout.Height(26));
            GUILayout.Label("任务编号", label);
            GUILayout.BeginHorizontal();
            taskId = GUILayout.TextField(taskId, GUILayout.Height(28));
            GUI.enabled = !following && !loader.IsLoading;
            if (GUILayout.Button("查询并加载", GUILayout.Width(100), GUILayout.Height(28))) FollowTask(taskId);
            GUILayout.EndHorizontal();
            GUI.enabled = true;
            if (following && GUILayout.Button("停止等待")) { polling?.Cancel(); }
            GUILayout.Space(8);
            GUILayout.Label("GLB 模型地址", label);
            modelUrl = GUILayout.TextField(modelUrl, GUILayout.Height(26));
            GUILayout.BeginHorizontal();
            GUI.enabled = !following && !loader.IsLoading;
            if (GUILayout.Button("加载模型", GUILayout.Height(28))) LoadModelUrl(modelUrl);
            if (GUILayout.Button("重试", GUILayout.Height(28))) LoadModelUrl(loader.LastUrl);
            GUI.enabled = true;
            if (GUILayout.Button("重置视角", GUILayout.Height(28))) viewer.ResetView();
            GUILayout.EndHorizontal();
            viewer.autoRotate = GUILayout.Toggle(viewer.autoRotate,"缓慢自动旋转");
            GUILayout.Label(string.IsNullOrEmpty(taskStatus) ? loader.Status : taskStatus + "\n" + loader.Status, hint);
            if (!string.IsNullOrEmpty(taskError) || !string.IsNullOrEmpty(loader.Error))
            {
                GUI.color = new Color(1,.55f,.4f);
                GUILayout.Label(taskError + " " + loader.Error, hint);
                GUI.color = Color.white;
            }
            GUILayout.Label("拖动旋转；滚轮或双指缩放。\n模拟模式显示带纹理的测试立方体，非真实重建结果。",hint);
            GUILayout.EndArea();
            GUI.skin = previousSkin;
            GUI.matrix = old;
        }

        // Stable UnitySendMessage entry points for a future Android host.
        public async void LoadModelUrl(string url)
        {
            polling?.Cancel();
            taskStatus = ""; taskError = ""; modelUrl = url;
            await loader.LoadModelAsync(url);
        }
        public async void FollowTask(string id)
        {
            if (following || loader.IsLoading) return;
            polling = new CancellationTokenSource();
            var source = polling;
            following = true; taskError = ""; taskId = id;
            try
            {
                var result = await api.WaitForModelAsync(id, task =>
                    taskStatus = (task.is_mock ? "模拟测试模型 | " : "AI 三维建模 | ") + PreviewText.TaskStatus(task.status), source.Token);
                source.Token.ThrowIfCancellationRequested();
                modelUrl = result.model_url;
                await loader.LoadModelAsync(modelUrl);
            }
            catch (OperationCanceledException) { if (this != null) taskStatus = "已停止等待，可用原任务编号继续查询。"; }
            catch (Exception exception) { if (this != null) taskError = exception.Message; }
            finally { following = false; source.Dispose(); if (polling == source) polling = null; }
        }
        public void SetBackendUrl(string url) { api.baseUrl = url.TrimEnd('/'); }
        public void ResetView(string unused) { viewer.ResetView(); }
        void OnDestroy()
        {
            polling?.Cancel();
            if (chineseSkin != null) Destroy(chineseSkin);
            if (chineseFont != null) Destroy(chineseFont);
        }
    }
}
