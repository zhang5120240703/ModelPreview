# 草编工艺品图像转 3D 与 Unity 预览 MVP

在现有 **Unity 6000.4.10f1 / URP 17.4** 工程上增量实现。Unity 工程仍位于根目录；Python 服务位于 `backend/`。原有 SampleScene 和用户修改保留。

## 立即运行免费流程

1. 在根目录 PowerShell 执行 `./scripts/start-backend.ps1`。首次运行安装 Python 3.12 依赖；默认 Provider 为 **mock**。
2. 打开 <http://127.0.0.1:8000/docs> 中文测试台，点击“选择照片”，上传 1–6 张 JPG/PNG（混元和 Mock 支持前、后、左、右、上、下六个面；Meshy 上限 4 张），再点击“上传并开始生成”；完成后复制“任务编号”或“模型下载地址”。
3. Unity 等待 Package Manager 安装 glTFast 6.15.1 和编译完成，选择菜单 **草编模型测试 → 创建或打开预览场景**，然后进入运行模式（Play）。
4. 测试界面填写“后端服务地址”（Editor 使用 `http://127.0.0.1:8000`），粘贴“任务编号”，点击 **查询并加载**。成功后自动显示模型。
5. 拖动旋转，滚轮/双指缩放，“重置视角”恢复视角，勾选“缓慢自动旋转”自动展示。也可以粘贴响应中的 `model_url` 到“GLB 模型地址”，直接点击“加载模型”，失败后点击“重试”。

**Mock 始终返回带棋盘纹理的测试立方体，不会重建上传的草编照片。** 上传图只参与文件校验与任务存储，真实重建可启用腾讯混元或 Meshy。已有 `.env` 时以其中的 Provider 为准，不一定是 Mock。

另一种可复现测试方式：服务启动后，在 `backend/` 执行 `.venv/Scripts/python.exe scripts/smoke.py`。它会上传一张自动生成的测试图片，轮询并下载真实 GLB，输出 task_id/model_url，可直接用于 Unity。

## 项目内容

| 路径 | 内容 |
| --- | --- |
| `backend/app` | FastAPI、SQLite、异步 worker、可切换 Provider |
| `backend/tests` | HTTP 验证、Mock 全流程、混元/Meshy 离线协议和恢复语义测试 |
| `Assets/GrassCraft/Scripts` | GLB 加载、资源清理、视角、Input System 触屏、测试 UI、API 客户端 |
| `Assets/GrassCraft/Editor` | 创建预览场景和开发 HTTP 配置菜单 |
| `Assets/GrassCraft/Tests` | 连接本地 Mock 服务的 Unity PlayMode 联调测试 |
| `samples` | 测试图片和测试 GLB（不是真实重建结果） |
| `docs/API.md` | APP 开发者 API 协议 |
| `docs/UNITY_SETUP.md` | Editor、Android 真机和故障排查 |
| `docs/APP_INTEGRATION.md` | Unity as a Library 与其他 APP 技术栈接入 |
| `docs/VALIDATION.md` | 实际验证记录与尚未验证项 |
| `docs/HUNYUAN_SETUP.md` | 腾讯官方 TokenHub 密钥配置、单图与多视图接入 |

## 验证

在 `backend/` 执行 `.venv/Scripts/python.exe -m pytest -q`。Unity 联调测试需要先启动 **Mock** 服务，再在 Test Runner 中运行 `PreviewPipelineTests` 的 PlayMode 测试。测试会上传新任务、检查嵌入纹理、错误重试、替换与卸载，并将模型渲染图写入 `TestResults/`。

## 切换真实 AI

腾讯混元：在项目根目录运行 `./scripts/configure-hunyuan.ps1`，按提示粘贴 **TokenHub API Key**（输入不回显），然后重启后端。打开中文测试台，先上传一张正面照片。默认使用 `hy-3d-3.1`、带颜色纹理、关闭额外 PBR；多视图需要配置公网 HTTPS 图片入口，详见 [混元接入说明](docs/HUNYUAN_SETUP.md)。

Meshy：在 `backend/.env` 设置 `PROVIDER=meshy`、`MESHY_API_KEY` 和可被客户端访问的 `PUBLIC_BASE_URL`，重启服务。Key 只保存在后端，不传给 Unity。真实任务会使用平台额度；创建任务不自动重试，以免重复付费。切回免费测试时设置 `PROVIDER=mock` 并重启。

MVP 使用**一个服务进程、一个串行 worker**。请勿使用多个 uvicorn workers；生产迁移与部署边界见 [后端说明](backend/README.md)。
