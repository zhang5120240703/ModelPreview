using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace GrassCraft
{
    [Serializable]
    public sealed class ReconstructionTask
    {
        public string task_id, status, status_url, model_url, error, provider;
        public bool is_mock;
        // JsonUtility cannot represent nullable numbers. UI uses status rather than inventing a percentage.
    }

    public sealed class ReconstructionApiClient : MonoBehaviour
    {
        public string baseUrl = "http://127.0.0.1:8000";
        public float pollSeconds = 3;
        public async Task<ReconstructionTask> GetTaskAsync(string id, CancellationToken token)
        {
            if (!Regex.IsMatch(id ?? "", @"\A[a-zA-Z0-9_-]{1,100}\z"))
                throw new ArgumentException("请输入有效的任务编号。");
            using (var request = UnityWebRequest.Get(baseUrl.TrimEnd('/') + "/api/v1/reconstructions/" + id))
                return await Send(request, token);
        }

        // Host apps normally upload directly. This method accepts already-read bytes, never a server path.
        // Default order: front, back, left, right, top, bottom. Supply views when selecting another order.
        public async Task<ReconstructionTask> UploadAsync(IReadOnlyList<byte[]> images,
            IReadOnlyList<string> filenames, CancellationToken token, IReadOnlyList<string> views = null)
        {
            if (images == null || filenames == null || images.Count < 1 || images.Count > 6 || filenames.Count != images.Count)
                throw new ArgumentException("请上传 1–6 张图片，并为每张图片提供对应文件名；默认顺序为前、后、左、右、上、下。");
            if (views != null)
            {
                var allowed = new HashSet<string> { "front", "back", "left", "right", "top", "bottom" };
                var selected = new HashSet<string>();
                if (views.Count != images.Count) throw new ArgumentException("每张图片必须对应一个视角。");
                foreach (var view in views)
                    if (!allowed.Contains(view) || !selected.Add(view))
                        throw new ArgumentException("视角只能为前、后、左、右、上、下，且不能重复。");
                if (!selected.Contains("front")) throw new ArgumentException("必须包含一张正面照片。");
            }
            var parts = new List<IMultipartFormSection>();
            for (int i = 0; i < images.Count; i++)
            {
                bool png = filenames[i].EndsWith(".png", StringComparison.OrdinalIgnoreCase);
                if (images[i].Length > 10 * 1024 * 1024) throw new ArgumentException("单张图片不能超过 10 MB。");
                parts.Add(new MultipartFormFileSection("images", images[i], filenames[i], png ? "image/png" : "image/jpeg"));
                if (views != null) parts.Add(new MultipartFormDataSection("views", views[i]));
            }
            using (var request = UnityWebRequest.Post(baseUrl.TrimEnd('/') + "/api/v1/reconstructions", parts))
                return await Send(request, token);
        }

        public async Task<ReconstructionTask> WaitForModelAsync(string id, Action<ReconstructionTask> changed,
            CancellationToken token)
        {
            float started = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - started < 1900)
            {
                var task = await GetTaskAsync(id, token);
                changed?.Invoke(task);
                if (task.status == "failed") throw new InvalidOperationException(task.error ?? "三维模型生成失败。");
                if (task.status == "succeeded")
                {
                    if (string.IsNullOrWhiteSpace(task.model_url)) throw new InvalidOperationException("任务已完成，但未返回模型下载地址。");
                    return task;
                }
                await Task.Delay(TimeSpan.FromSeconds(Mathf.Clamp(pollSeconds, 2, 30)), token);
            }
            throw new TimeoutException("等待已超过 1900 秒，可使用原任务编号重新查询。");
        }

        static async Task<ReconstructionTask> Send(UnityWebRequest request, CancellationToken token)
        {
            request.timeout = 30;
            var operation = request.SendWebRequest();
            using (token.Register(request.Abort))
            {
                while (!operation.isDone) { token.ThrowIfCancellationRequested(); await Task.Yield(); }
            }
            token.ThrowIfCancellationRequested();
            if (request.result != UnityWebRequest.Result.Success)
                throw new InvalidOperationException("接口请求失败：" + PreviewText.NetworkError(request));
            var result = JsonUtility.FromJson<ReconstructionTask>(request.downloadHandler.text);
            if (result == null || string.IsNullOrEmpty(result.task_id)) throw new InvalidOperationException("服务器返回的数据格式不正确。");
            return result;
        }
    }
}
