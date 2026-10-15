# 免费测试素材

`test-photo.png` 是自动生成的纯色测试图片，`mock-textured-cube.glb` 是后端通过真实 HTTP 流程下载的带棋盘纹理立方体。两者均用于接口和加载验证，不代表任何真实草编作品或 AI 重建质量。

`task.json` 记录本次本地测试响应；该任务 ID 只在本机 backend/data 未清理时有效。重新测试请运行 backend/scripts/smoke.py 获取新 ID。也可在 samples 目录启动 `py -3.12 -m http.server 8001`，Unity URL 填 `http://127.0.0.1:8001/mock-textured-cube.glb`，独立验证 GLB 加载。
