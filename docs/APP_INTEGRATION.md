# 未来 APP 集成

拍照/图库和业务 UI 属于 APP；它只需要 REST 上传、task_id 查询和标准 GLB 下载。后端不依赖 APP 框架，Unity 也可直接接收 model_url。先用独立 Unity 预览验证，不在当前阶段绑定 Android 原生、Flutter 或 uni-app。

## Android 原生 + Unity as a Library

1. Unity Android Build Profiles 选择 Export Project，导出 Gradle 工程，生成 `unityLibrary` 与启动壳 `launcher`。
2. 宿主 Android 项目在 settings.gradle 引入 unityLibrary，并在应用模块添加依赖；协调 Gradle/AGP、SDK、NDK、ABI、清单和资源配置。不要把完整 launcher 当作嵌入模块。
3. 通过 Intent 启动 Unity Activity；在 Unity 初始化和场景就绪后调用 `UnityPlayer.UnitySendMessage("GrassCraftPreview", "LoadModelUrl", modelUrl)`。也可先调用 `SetBackendUrl`，再调用 `FollowTask` 传入 task_id。`ResetView` 接受空字符串。
4. 宿主负责等待 Unity 就绪（当前未实现 Java 回调桥）、传递配置并管理 Activity 的暂停、恢复、焦点、返回和退出。结果回传可后续通过 AndroidJavaObject/接口回调桥实现。

示例：

```java
UnityPlayer.UnitySendMessage("GrassCraftPreview", "SetBackendUrl", "https://api.example.com");
UnityPlayer.UnitySendMessage("GrassCraftPreview", "FollowTask", taskId);
// 已有成功模型时直接 LoadModelUrl，无需查询后端。
```

根据 [Unity 6 Android 官方集成说明](https://docs.unity3d.com/6000.0/Documentation/Manual/UnityasaLibrary-Android.html)，普通 Unity as a Library 仅支持全屏渲染、一个 Unity runtime 实例；不能假设它能嵌在普通列表卡片里。Application.Unload / UnityPlayer.unload 会卸载场景并保留部分运行时内存；quit 可能结束运行 Unity 的进程，宿主应按产品导航设计卸载和返回，不能把 quit 当作普通关闭页面。

引入 Unity runtime、URP、原生库和 shader 会增加 APK/AAB、启动时间及内存。没有固定通用增量大小，必须对实际 Release/ARM64 构建测量；减少无用包、场景、架构和 shader 变体，并测试相机/音频与其他原生插件的生命周期兼容性。当前交付没有完成宿主 Gradle 工程或原生生命周期桥。

## Flutter / uni-app

两条路线都保留：

- 通过原生桥接启动 Unity 全屏预览，沿用上面的 runtime/lifecycle 限制，检查所选第三方 Flutter/uni-app 桥是否支持当前 Unity 版本。
- 直接将 GLB model_url 交给 WebView 中的成熟 glTF 查看器或框架对应 3D 查看器，适合轻量独立展示；配置 HTTPS、CORS、WebGL 支持与触摸/内存策略。当前未交付 WebView 查看器，也未引入第三方桥插件。

选择依据是场景复杂度、包体、全屏需求、设备性能和团队技术栈。无论采用哪条路线，都必须向用户标识 is_mock=true 是测试模型，不是拍摄物体重建结果。
