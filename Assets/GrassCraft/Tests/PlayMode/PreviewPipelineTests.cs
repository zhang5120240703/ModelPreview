using System;
using System.Collections;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using GrassCraft;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using UnityEngine.Networking;

public class PreviewPipelineTests
{
    [Test]
    public void InactiveOffsetChildIsCenteredAndNormalized()
    {
        var root = new GameObject("Inactive staging root");
        root.SetActive(false);
        var child = GameObject.CreatePrimitive(PrimitiveType.Cube);
        child.transform.SetParent(root.transform, false);
        child.transform.localPosition = new Vector3(5,2,-3);
        child.transform.localScale = new Vector3(2,4,6);
        try
        {
            var bounds = ModelBoundsHelper.Normalize(root.transform);
            Assert.That(child.transform.position.magnitude, Is.LessThan(.001f));
            Assert.That(Mathf.Max(bounds.size.x,bounds.size.y,bounds.size.z), Is.EqualTo(2).Within(.001f));
        }
        finally { UnityEngine.Object.DestroyImmediate(root); }
    }

    static IEnumerator Wait(Task task, float seconds = 120)
    {
        float start = Time.realtimeSinceStartup;
        while (!task.IsCompleted && Time.realtimeSinceStartup-start < seconds) yield return null;
        Assert.IsTrue(task.IsCompleted, "操作超时");
        if (task.IsFaulted) throw task.Exception;
        Assert.IsFalse(task.IsCanceled);
    }

    [UnityTest]
    public IEnumerator UploadPollLoadTextureRetryReplaceAndUnload()
    {
        string testBaseUrl = Environment.GetEnvironmentVariable("GRASSCRAFT_TEST_BASE_URL") ?? "http://127.0.0.1:8000";
        using (var health = UnityWebRequest.Get(testBaseUrl.TrimEnd('/') + "/health"))
        {
            health.timeout = 10;
            yield return health.SendWebRequest();
            Assert.AreEqual(UnityWebRequest.Result.Success, health.result, "请先启动模拟测试后端。");
            StringAssert.Contains("\"provider\":\"mock\"", health.downloadHandler.text,
                "联调测试必须使用模拟模式，不允许提交付费任务。");
        }
        var host = new GameObject("Smoke preview");
        host.AddComponent<PreviewBootstrap>();
        yield return null;
        var api = host.GetComponent<ReconstructionApiClient>();
        api.baseUrl = testBaseUrl;
        var loader = host.GetComponent<ModelLoader>();
        var viewer = host.GetComponent<ModelViewerController>();
        viewer.autoRotate = false;
        var photo = new Texture2D(8,8);
        byte[] image = photo.EncodeToPNG();
        UnityEngine.Object.Destroy(photo);
        var upload = api.UploadAsync(new[] { image, image, image, image, image, image },
            new[] { "front.png", "back.png", "left.png", "right.png", "top.png", "bottom.png" },
            CancellationToken.None, new[] { "front", "back", "left", "right", "top", "bottom" });
        yield return Wait(upload);
        Assert.IsTrue(upload.Result.is_mock, "联调测试需要设置 PROVIDER=mock，避免提交付费任务。");
        var poll = api.WaitForModelAsync(upload.Result.task_id, null, CancellationToken.None);
        yield return Wait(poll);
        Assert.AreEqual("succeeded",poll.Result.status);
        var load = loader.LoadModelAsync(poll.Result.model_url);
        yield return Wait(load);
        Assert.IsTrue(load.Result, loader.Error);
        var renderer = loader.Pivot.GetComponentInChildren<Renderer>();
        Assert.IsNotNull(renderer);
        Assert.IsNotNull(renderer.sharedMaterial);
        Assert.IsNotNull(renderer.sharedMaterial.mainTexture, "导入后必须保留内嵌测试纹理。");
        Assert.That(renderer.bounds.size.magnitude, Is.GreaterThan(1));
        float before = Vector3.Distance(viewer.viewCamera.transform.position, Vector3.zero);
        viewer.Zoom(1000);
        viewer.Rotate(new Vector2(20,10));
        yield return null;
        Assert.That(Vector3.Distance(viewer.viewCamera.transform.position, Vector3.zero), Is.LessThan(before));
        viewer.ResetView();
        yield return null;
        Assert.That(Vector3.Distance(viewer.viewCamera.transform.position, Vector3.zero), Is.EqualTo(before).Within(.01f));
        SaveRender(viewer.viewCamera);
        var failed = loader.LoadModelAsync(api.baseUrl + "/api/v1/models/missing/file");
        yield return Wait(failed);
        Assert.IsFalse(failed.Result);
        Assert.IsNotNull(loader.Pivot.GetComponentInChildren<Renderer>(), "模型替换失败时必须保留原模型。");
        var retry = loader.LoadModelAsync(poll.Result.model_url);
        yield return Wait(retry);
        Assert.IsTrue(retry.Result, loader.Error);
        yield return null;
        Assert.AreEqual(1,loader.Pivot.GetComponentsInChildren<Renderer>().Length);
        loader.UnloadModel();
        yield return null;
        Assert.AreEqual(0,loader.Pivot.GetComponentsInChildren<Renderer>().Length);
        UnityEngine.Object.Destroy(viewer.viewCamera.gameObject);
        UnityEngine.Object.Destroy(host);
        foreach (var light in UnityEngine.Object.FindObjectsByType<Light>(FindObjectsSortMode.None))
            UnityEngine.Object.Destroy(light.gameObject);
    }

    static void SaveRender(Camera camera)
    {
        var target = new RenderTexture(800,800,24);
        var previous = RenderTexture.active;
        var rect = camera.rect;
        camera.rect = new Rect(0,0,1,1);
        camera.targetTexture = target;
        camera.Render();
        RenderTexture.active = target;
        var texture = new Texture2D(800,800,TextureFormat.RGB24,false);
        texture.ReadPixels(new Rect(0,0,800,800),0,0);
        texture.Apply();
        Directory.CreateDirectory("TestResults");
        File.WriteAllBytes("TestResults/mock-preview.png",texture.EncodeToPNG());
        camera.targetTexture = null;
        camera.rect = rect;
        RenderTexture.active = previous;
        UnityEngine.Object.Destroy(texture);
        target.Release();
        UnityEngine.Object.Destroy(target);
    }
}
