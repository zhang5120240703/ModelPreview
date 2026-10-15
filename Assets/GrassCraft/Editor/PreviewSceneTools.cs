using System.Linq;
using GrassCraft;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class PreviewSceneTools
{
    public const string ScenePath = "Assets/GrassCraft/Scenes/GrassCraftPreview.unity";
    [MenuItem("草编模型测试/创建或打开预览场景")]
    public static void CreateScene()
    {
        if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
        if (System.IO.File.Exists(ScenePath)) EditorSceneManager.OpenScene(ScenePath);
        else
        {
            System.IO.Directory.CreateDirectory("Assets/GrassCraft/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            new GameObject("GrassCraftPreview").AddComponent<PreviewBootstrap>();
            EditorSceneManager.SaveScene(scene, ScenePath);
        }
        var scenes = EditorBuildSettings.scenes.ToList();
        if (!scenes.Any(s => s.path == ScenePath)) scenes.Add(new EditorBuildSettingsScene(ScenePath, true));
        EditorBuildSettings.scenes = scenes.ToArray();
    }

    [MenuItem("草编模型测试/允许开发版本使用 HTTP")]
    public static void AllowDevelopmentHttp()
    {
        PlayerSettings.insecureHttpOption = InsecureHttpOption.DevelopmentOnly;
        Debug.Log("已允许开发版本使用 HTTP。正式发布版本请使用 HTTPS。");
    }
}
