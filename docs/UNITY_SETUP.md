# Unity Editor / Android 运行指南

## 工程与场景

已检测 Unity **6000.4.10f1**、URP **17.4.0**、Input System **1.19.0**，并保留既有工程。`Packages/manifest.json` 增加 `com.unity.cloud.gltfast: 6.15.1`。需要联网完成首次依赖下载。

1. 打开工程，等待 Package Manager 和脚本编译。若未刷新，点击 Unity 窗口或 Assets → Refresh。
2. 菜单 **草编模型测试 → 创建或打开预览场景**。场景只含 Bootstrap，其在运行时创建中性背景、环境光、两盏无阴影方向光、摄像机和独立组件。原 SampleScene 不会被改写；首次创建会询问保存当前场景，并把新场景加入 Build Settings。
3. 进入运行模式，在“后端服务地址”输入后端地址，“任务编号”输入框粘贴任务 ID，点击“查询并加载”；或者输入完整的“GLB 模型地址”，点击“加载模型”。
4. 拖动旋转、滚轮缩放、“重置视角”、“缓慢自动旋转”均可用。移动端同一 Rotate/Zoom 逻辑支持单指/双指，界面区域不触发模型拖拽。

测试 UI 使用轻量 IMGUI，作为独立联调入口；未来 APP 可以替换它。暂未加入手机相机和图库选择器，APP 负责选图后上传，或调用 `UploadAsync` 提交字节。混元支持最多六张，默认按前、后、左、右、上、下排列；也可通过可选的 views 参数显式传 front/back/left/right/top/bottom，与每张图片一一对应且包含正面。服务端最终数量和大小限制以 /health 为准，Meshy/fal 仍最多四张。

测试界面的按钮、状态和错误提示均为中文。Editor 优先使用系统中的微软雅黑、黑体等中文字体，移动端尝试 Noto CJK / Droid Sans Fallback。若目标设备缺少这些系统字体，需要按字体许可在项目中加入中文字体并调整字体加载配置；Android 中文显示仍需真机确认。

## 脚本职责

| 脚本 | 职责 |
| --- | --- |
| ModelLoader | 限大小下载、GLB 检查、glTFast 异步导入、失败保留旧模型、替换/卸载 Dispose |
| ModelBoundsHelper | 可见网格包围盒、居中与最大尺寸归一化 |
| ModelViewerController | 共享旋转缩放、摄像机适配、输入区域、缩放限制、自动转动 |
| ReconstructionApiClient | multipart 上传、任务查询、限频等待、超时和取消 |
| ModelPreviewUI | URL/task 测试 UI 与 UnitySendMessage 方法 |
| PreviewBootstrap | 简洁场景和组件组装 |

使用 [glTFast 官方运行时加载接口](https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.15/manual/ImportRuntime.html)。调用 Load(byte[], uri, cancellationToken)、InstantiateMainSceneAsync，加载新模型成功后替换旧实例，并 Dispose 释放导入资源。下载限制默认 64 MiB，不等于峰值内存限制；同时保留新旧模型会提高峰值。场景销毁时取消请求。导入日志在 Console，可发现部分纹理失败等非致命问题。

## Android 构建

1. Unity Hub 为此版本安装 Android Build Support、SDK/NDK、OpenJDK（当前机器检测到 AndroidPlayer 目录，真机/构建仍需实际验证）。
2. Build Profiles 新建 Android，切换平台；只勾选 GrassCraftPreview，并把它放首位；Player Settings 使用 IL2CPP / ARM64，Internet Access 设 Require，Input Handling 保持 Input System。设置自己的应用标识。
3. 局域网开发选菜单 **草编模型测试 → 允许开发版本使用 HTTP**，勾 Development Build。Unity 默认禁止 HTTP，本菜单只对开发版放行，不会全局关闭发布版限制。若目标 Android 清单另有 cleartext 限制，检查最终合并清单的 `android:usesCleartextTraffic` 与网络配置，或直接使用受信任 HTTPS。
4. 后端 `.env` 设置 `PUBLIC_BASE_URL=http://电脑局域网IP:8000`，执行根脚本 `./scripts/start-backend.ps1 -BindAddress 0.0.0.0`，按系统提示配置防火墙；手机浏览器先测试 `/health`。
5. 打开 APP，“后端服务地址”同样填写电脑局域网 IP。模拟器使用 `http://10.0.2.2:8000`，同时更改 PUBLIC_BASE_URL 并重启后端。
6. 正式构建使用 HTTPS，清除开发放行需求。测试暂停/恢复、断网重试、屏幕旋转、连续模型替换和低内存情况。

## 材质打包与性能

Editor 可即时编译 shader，Android 构建可能剥离运行时需要的 shader variants。发布前按 [glTFast 官方 Project Setup](https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.15/manual/ProjectSetup.html) 在 Editor 加载代表性 GLB，将 Graphics → Shader Preloading 中跟踪的变体保存为 ShaderVariantCollection，加入 Preloaded Shaders。也可以用 Resources 内的代表性材质保留所需变体，避免无选择保留所有变体导致包体膨胀。至少覆盖金属粗糙度、法线、透明/双面等实际会接收的材质；构建后真机验证纹理和 shader。

起点为约 30000 三角面、2K 纹理，不承诺所有手机都适合。使用 Profiler 量测 GPU/CPU 和峰值内存；大模型考虑服务端降面、纹理压缩、LOD 和对象存储 CDN。此版本未启用 Draco/KTX 可选解码插件，平台结果若含这些压缩扩展，需要按 glTFast 文档安装相应插件并回归测试。

## 自动联调测试

启动 127.0.0.1:8000 的 Mock 服务，在 Window → General → Test Runner → PlayMode 运行 `PreviewPipelineTests`。测试会产生上传任务并渲染 `TestResults/mock-preview.png`。默认测试后端固定为本机，不要把此测试用于真实付费 Provider。

常见故障：连接失败先访问 /health；model_url 错误先检查 PUBLIC_BASE_URL；粉色模型检查 shader variants 和 URP；无模型检查任务是否失败、Unity Console、文件大小和 GLB 内容；触摸无效检查 Input System 及操作是否始于展示区域。
