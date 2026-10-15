# 实际验证记录

日期：2026-10-15（北京时间）。在 Windows、Python 3.12 和 Unity 6000.4.10f1 / URP 17.4.0 下执行。

## 已验证

| 检查 | 实际结果 / 证据 |
| --- | --- |
| Python 自动化测试 | 48 passed（包含六图完整流程、顶底面映射、重复/非法视角、七张拒绝、其他 Provider 四张限制）；见 test-results/backend-pytest.txt 与 backend.xml |
| 真实 HTTP 服务 | uvicorn 在 127.0.0.1:8000 启动，smoke.py 上传、轮询并下载 2140 字节的自包含 GLB；响应见 ../samples/task.json |
| Unity 脚本编译 | Unity 6.4 批处理编译成功，生成可打开的 GrassCraftPreview 场景 |
| Unity PlayMode | 2 passed / 0 failed，见 test-results/unity-playmode.xml |
| 端到端加载 | Unity 实际调用本地 HTTP 上传、查询、下载，glTFast 运行时导入成功，材质及内嵌 PNG 非空 |
| 模型生命周期 | 错误 URL 保留旧模型，成功重试、替换、卸载检查通过 |
| 视角与包围盒 | 缩放范围和重置逻辑通过；inactive + 子节点偏移/非均匀尺寸的归一化通过 |
| 模型渲染 | Unity 摄像机生成 test-results/mock-preview.png，已查看确认棋盘纹理可见 |
| 中文测试台 | 已在实际浏览器完成选图、上传和自动查询，显示“模型已生成”，见 test-results/chinese-test-page.jpg；页面无需外部脚本或 CDN |
| Meshy 离线协议 | 使用 httpx MockTransport 检查 data URI、请求字段、任务 ID、状态、下载不携带 Key，以及 400/401/402/429/500、缺 Key 和非法下载域名 |
| 混元离线协议与全流程 | 模拟 TokenHub 验证单图原始 Base64、多视图命名与临时 URL、状态转换、重启后模型凭据、查询重试、缺密钥/额度/权限错误、GLB 下载及完整 FastAPI worker 流程；未请求真实云端 |
| 混元中文页面 | 本地 8001 端口实际浏览器检查：密钥缺失时禁用提交，照片预览与中文视角正常，无浏览器控制台错误；见 test-results/hunyuan-test-page.png。检查后已停止临时服务 |
| 六面浏览器流程 | 8002 隔离 Mock 服务：六图选取、六种默认标注、上传、自动轮询至成功，见 test-results/six-view-mock.png。实际 8000 混元服务已重启并确认 max_images=6，仅选图检查未提交，见 test-results/six-view-hunyuan.png |
| 混元真实单图任务 | 用户自行提交的任务 7e444447767d4671a8928a9e02647117 已 succeeded；GLB 已通过后端校验并保存，31893320 字节。本次检查未新增云端任务，未检查账单和重建视觉质量 |

Unity 验证使用 `Verification/UnityProject` 隔离副本，避免改动当前 Editor 场景。首次官方包缓存写入遭遇 EBADF，验证副本改用从 Unity 官方 registry 下载的相同 glTFast 6.15.1 包作为 embedded package；主工程仍使用 registry 依赖，之后已正常解析安装。隔离副本不属于交付源码，也不提交。

后端测试有 1 条 Starlette 关于 TestClient/httpx 的弃用警告，不影响本次通过；将来升级测试传输时需回归。实际依赖版本已固定在 backend/requirements-lock.txt。

中文化阶段运行 16 项后端测试和 2 项 Unity PlayMode 测试，全部通过。混元初次适配后后端扩展为 40 项，六面扩展后为 48 项并全部通过。本次 Unity 上传客户端已扩展至六张并支持可选视角参数，PlayMode 联调用例已改为六张图及六个视角，但批处理启动被自动审批拒绝，未提供具体原因，因此没有本次 Unity 编译/运行通过的结论；上表 Unity 结果为此前记录。Unity 菜单、输入说明、按钮、任务状态及常见网络错误已中文化，接口字段及机器状态代码保持兼容。中文字体通过系统字体回退加载，Android 字形显示尚需目标设备确认。原生 Swagger 技术文档保留于 /docs/swagger，普通测试入口 /docs 为完整中文测试页面。

## 已实现、仍需人工/外部环境验证

- 鼠标/触屏输入路由与自动旋转已有实现；自动化验证了共享 Rotate/Zoom 逻辑，尚未进行真实手机手势和长时间交互流畅度测试。
- 未执行 Android APK/AAB 构建、ARM64/IL2CPP 运行或低内存测试；adb devices 未发现设备。AndroidPlayer SDK/NDK/OpenJDK 目录存在。
- Meshy Provider 已实现，**未提交任何真实云端 AI 任务**。需要服务器 MESHY_API_KEY 与额度，验证图片重建质量、实际模型扩展、素材下载域名和移动端资源开销。
- 腾讯混元 TokenHub 已实现，默认 hy-3d-3.1；用户已配置密钥并完成一次真实单图生成。**六图真实生成、多视图公网可达性、真实草编重建视觉质量和腾讯 GLB 在 Unity 的实际表现仍未验证**。当前 public_images_configured=false，多图会在付费提交前被拦截。
- TripoProvider 仅为明确报“尚未接入”的扩展占位，没有伪装成可用服务。
- Android 原生宿主、Unity as a Library 生命周期桥、Flutter/uni-app 桥与 WebView 查看器尚未开发，本次只提供稳定接入入口及说明。
- 生产身份认证、任务所有权、持久队列和对象存储尚未实现，当前后端按单进程可信开发环境运行。

## 你在 Editor 中需要做的事

等待依赖与脚本刷新，打开 `Assets/GrassCraft/Scenes/GrassCraftPreview.unity` 或菜单“草编模型测试 → 创建或打开预览场景”，进入运行模式；填入“后端服务地址”和“任务编号”后点击“查询并加载”。无需手工拖拽脚本或连接组件。

Android 构建前需要选择目标场景与平台、Internet Access、ARM64/IL2CPP、采集/保留 glTF shader variants；局域网开发版通过菜单启用 HTTP，设置电脑局域网地址并验证防火墙。完整步骤见 UNITY_SETUP.md。

**图中的立方体是程序生成的 Mock 测试模型，不是草编工艺品的 AI 重建结果。**
