using System;
using UnityEngine.Networking;

namespace GrassCraft
{
    // Translate presentation text while keeping REST status codes and fields stable.
    public static class PreviewText
    {
        public static string TaskStatus(string status)
        {
            switch (status)
            {
                case "queued": return "排队中";
                case "processing": return "生成中";
                case "succeeded": return "已完成";
                case "failed": return "生成失败";
                default: return "未知任务状态";
            }
        }

        public static string NetworkError(UnityWebRequest request)
        {
            if (request.responseCode > 0)
            {
                string reason;
                switch (request.responseCode)
                {
                    case 400: case 422: reason = "请求参数不正确"; break;
                    case 401: case 403: reason = "服务器拒绝访问，请检查权限"; break;
                    case 404: reason = "地址或任务不存在"; break;
                    case 409: reason = "模型尚未生成成功"; break;
                    case 413: reason = "文件超过大小限制"; break;
                    case 415: reason = "图片或模型格式不受支持"; break;
                    case 429: reason = "请求过于频繁，请稍后重试"; break;
                    default: reason = "服务器处理异常，请稍后重试"; break;
                }
                return reason + "（HTTP " + request.responseCode + "）。";
            }
            if ((request.error ?? "").IndexOf("timeout", StringComparison.OrdinalIgnoreCase) >= 0 ||
                (request.error ?? "").IndexOf("timed out", StringComparison.OrdinalIgnoreCase) >= 0)
                return "网络请求超时，请检查连接后重试。";
            return "网络连接失败，请检查后端地址、网络及 HTTP/HTTPS 设置。";
        }
    }
}
