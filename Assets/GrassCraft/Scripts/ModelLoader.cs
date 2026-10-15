using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using GLTFast;
using GLTFast.Logging;
using UnityEngine;
using UnityEngine.Networking;

namespace GrassCraft
{
    public sealed class ModelLoader : MonoBehaviour
    {
        public int maxDownloadMegabytes = 64;
        public bool IsLoading { get; private set; }
        public string Status { get; private set; } = "准备就绪，请输入模型地址或任务编号。";
        public string Error { get; private set; } = "";
        public string LastUrl { get; private set; } = "";
        public Transform Pivot { get; private set; }
        public event Action<Bounds> Loaded;
        GltfImport current;
        GameObject currentRoot;
        CancellationTokenSource lifetime;

        void Awake()
        {
            Pivot = new GameObject("ModelPivot").transform;
            Pivot.SetParent(transform, false);
            lifetime = new CancellationTokenSource();
        }

        // Serialize requests to cap peak model memory and avoid stale loads replacing new models.
        public async Task<bool> LoadModelAsync(string url)
        {
            if (IsLoading || lifetime == null) return false;
            IsLoading = true;
            Error = "";
            LastUrl = url;
            GltfImport candidate = null;
            GameObject root = null;
            var token = lifetime.Token;
            try
            {
                if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) ||
                    (uri.Scheme != "http" && uri.Scheme != "https"))
                    throw new InvalidOperationException("请输入以 HTTP 或 HTTPS 开头的完整模型地址。");
                Status = "正在下载 GLB 模型……";
                byte[] bytes;
                var handler = new LimitedDownload(maxDownloadMegabytes * 1024L * 1024L);
                try
                {
                    using (var request = new UnityWebRequest(url, "GET", handler, null))
                    {
                        request.timeout = 90;
                        var operation = request.SendWebRequest();
                        using (token.Register(request.Abort))
                        {
                            while (!operation.isDone) { token.ThrowIfCancellationRequested(); await Task.Yield(); }
                        }
                        token.ThrowIfCancellationRequested();
                        if (handler.Exceeded) throw new InvalidOperationException("模型文件超过下载大小限制。");
                        if (request.result != UnityWebRequest.Result.Success)
                            throw new InvalidOperationException("模型下载失败：" + PreviewText.NetworkError(request));
                        bytes = handler.GetBytes();
                    }
                }
                finally { handler.Release(); }
                if (bytes.Length < 20 || bytes[0] != 'g' || bytes[1] != 'l' || bytes[2] != 'T' || bytes[3] != 'F' ||
                    BitConverter.ToUInt32(bytes, 4) != 2 || BitConverter.ToUInt32(bytes, 8) != bytes.Length)
                    throw new InvalidOperationException("下载结果不是有效的 GLB 2.0 模型文件。");
                Status = "正在加载模型网格和纹理……";
                candidate = new GltfImport(logger: new ConsoleLogger());
                if (!await candidate.Load(bytes, uri, cancellationToken: token))
                    throw new InvalidOperationException("模型导入失败，请在 Unity 控制台查看详细原因。");
                token.ThrowIfCancellationRequested();
                // Inactive staging hierarchy keeps the previous model visible on failure.
                root = new GameObject("GLB content");
                root.SetActive(false);
                // Stage at world origin so viewer rotation cannot affect asynchronous bounds calculation.
                if (!await candidate.InstantiateMainSceneAsync(root.transform, cancellationToken: token))
                    throw new InvalidOperationException("GLB 模型没有可加载的主场景。");
                token.ThrowIfCancellationRequested();
                Bounds bounds = ModelBoundsHelper.Normalize(root.transform);
                foreach (var light in root.GetComponentsInChildren<Light>(true)) light.enabled = false;
                foreach (var camera in root.GetComponentsInChildren<Camera>(true)) camera.enabled = false;
                root.transform.SetParent(Pivot, false);
                UnloadModel();
                current = candidate; candidate = null;
                currentRoot = root; root = null;
                currentRoot.SetActive(true);
                Status = "模型加载完成，可以拖动旋转、滚轮或双指缩放。";
                Loaded?.Invoke(bounds);
                return true;
            }
            catch (OperationCanceledException) { return false; }
            catch (Exception exception)
            {
                if (this != null) { Error = exception.Message; Status = "加载失败，请检查模型地址和网络后点击“重试”。"; }
                return false;
            }
            finally
            {
                if (root != null) { root.SetActive(false); Destroy(root); }
                candidate?.Dispose();
                IsLoading = false;
            }
        }

        public void UnloadModel()
        {
            if (currentRoot != null) { currentRoot.SetActive(false); Destroy(currentRoot); currentRoot = null; }
            current?.Dispose(); current = null;
        }

        void OnDestroy()
        {
            lifetime?.Cancel(); lifetime?.Dispose(); lifetime = null;
            UnloadModel();
        }

        sealed class LimitedDownload : DownloadHandlerScript
        {
            readonly MemoryStream buffer = new MemoryStream();
            readonly long limit;
            public bool Exceeded { get; private set; }
            public LimitedDownload(long limit) : base(new byte[64 * 1024]) { this.limit = limit; }
            protected override void ReceiveContentLengthHeader(ulong length) { Exceeded = length > (ulong)limit; }
            protected override bool ReceiveData(byte[] data, int length)
            {
                if (Exceeded || buffer.Length + length > limit) { Exceeded = true; return false; }
                if (data != null && length > 0) buffer.Write(data, 0, length);
                return true;
            }
            public byte[] GetBytes() => buffer.ToArray();
            public void Release() => buffer.Dispose();
        }
    }
}
