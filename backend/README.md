# FastAPI 后端

推荐 Python 3.12。不要使用 PATH 中可能存在的嵌入式 Python。根目录 `scripts/start-backend.ps1` 自动创建虚拟环境；手动方式如下（在 backend 目录）：

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

`.env` 可省略，默认免费 Mock。依赖的宽版本范围在 requirements.txt，实际验证版本固定于 requirements-lock.txt。

## 配置

| 变量 | 默认 / 含义 |
| --- | --- |
| PROVIDER | mock；腾讯官方混元为 hunyuan，另支持 meshy；tripo 仍是占位 |
| PUBLIC_BASE_URL | http://127.0.0.1:8000；应改为目标客户端可访问地址 |
| DATA_DIR | 默认 backend/data，保存 SQLite 和任务独立文件夹；显式相对路径按启动目录解析 |
| MOCK_DELAY_SECONDS | 2；模拟等待时间，不代表 AI 真实进度 |
| MESHY_API_KEY | 仅服务端环境变量；也可由本地 .env 读取 |
| MESHY_AI_MODEL | latest；如需稳定行为可固定官方支持模型 |
| HUNYUAN_API_KEY | 腾讯 TokenHub API Key，仅保存在服务端；可用根目录 scripts/configure-hunyuan.ps1 隐藏输入 |
| HUNYUAN_MODEL | hy-3d-3.1；也支持 hy-3d-3.0 |
| HUNYUAN_ENABLE_PBR | false；默认生成颜色纹理，不启用额外 PBR |
| HUNYUAN_FACE_COUNT | 留空，使用平台默认；如需覆盖允许 3000–1500000，可能影响计费 |
| HUNYUAN_IMAGE_BASE_URL | 多视图的公网 HTTPS 图片入口；留空时尝试 PUBLIC_BASE_URL，单图不需要 |
| HUNYUAN_MODEL_DOWNLOAD_HOSTS | hunyuan-prod-1258344699.cos.ap-guangzhou.tencentcos.cn；下载精确主机白名单 |
| POLL_INTERVAL_SECONDS | 5；后端查询云端任务的间隔 |
| TASK_TIMEOUT_SECONDS | 1800；每次 worker 执行任务的超时 |
| MAX_IMAGE_MB | 通用默认 10 / 张；混元接入额外限制最多 4 MiB / 张。混元和 Mock 最多六张，Meshy/fal 最多四张 |
| MAX_MODEL_MB | 64；下载文件上限 |
| MODEL_DOWNLOAD_HOSTS | assets.meshy.ai；精确主机白名单，逗号分隔 |
| CORS_ORIGINS | 默认空；WebView/浏览器跨域时配置明确的页面 origin |

## 任务生命周期与恢复

上传校验并落盘后写入 SQLite，立即返回 202 queued。独立 asyncio worker 扫描已入库任务，串行执行；网络调用异步，图片解码/校验放在线程中，避免占用 HTTP 主线程。请求总字节有硬上限（当前 Provider 的图片数量 × 单张大小上限 + 1 MB multipart 开销），不信任 Content-Length；也限制 MIME、扩展名、真实解码和 2400 万像素。原始文件名不参与服务器路径。

worker 提交前写 processing，提交成功后立即保存远程 ID。重启会恢复 queued，并继续查询有 remote_id 的 processing 任务；processing 但没有 remote_id 时标记失败，要求先查平台，防止不确定提交重复扣费。切换 Provider 后旧任务不会自动发给新 Provider。重启后超时计时重新开始，这是 MVP 限制。

GLB 先下载到 model.part，校验 GLB 2.0 头、JSON 和自包含要求后，原子替换为 model.glb，最后标记 succeeded。不是完整的 glTF 语义验证器；Unity 加载时仍处理资源或几何错误。下载不向素材服务器发送 Key，不跟随跳转，不接受非 HTTPS 或白名单外主机。若平台改变素材域名，先核对官方结果再更改白名单。

## 腾讯混元 TokenHub

完整步骤见 [混元接入说明](../docs/HUNYUAN_SETUP.md)。参考 [腾讯官方 HY-3D 接口](https://cloud.tencent.com/document/product/1823/137181)，使用 Bearer API Key，调用 `/v1/api/3d/submit` 和 `/v1/api/3d/query`。单图发送原始 Base64，多图发送带临时令牌的公网图片 URL，并明确标注 front/back/left/right/top/bottom。正面使用 image_url，其余最多五个面使用 multi_view_images；允许少于六张，但必须有正面且视角不重复。

创建请求不自动重试；查询遇到网络错误、429 或部分 5xx，最多容忍连续三次后按轮询间隔继续查询，第四次失败。远程模型与任务编号一起保存，重启继续查询时不会因配置切换而查错模型。平台未提供数字进度，等待期间 progress=null。完成后提取 GLB，下载和校验成功后才公布本地模型地址。

多图的图片链接仅在任务排队/执行时有效，且有超时。默认本地地址不能被腾讯读取，会在提交前拦截。此功能不自动创建公网隧道，也不改变付费接口的访问控制要求。

## Meshy

以 2026-10-15 查阅的 [官方 Multi-Image to 3D API](https://docs.meshy.ai/en/api/multi-image-to-3d) 为依据：POST `/openapi/v1/multi-image-to-3d`，通过 `image_urls` 提交 1–4 张图片的 data URI；保存 `result`，GET 同路径 `/{id}` 查询 `status` / `progress` / `model_urls.glb`。

请求启用纹理、PBR、GLB、三角网格重拓扑，目标 30000 面与 2K 纹理。目标面数不保证精确，需要真机量测。无远程进度时本地 progress=null；本地文件完成前进度最多 99。认证、额度、限流、远程失败、超时和错误下载均写入任务错误。限流或 POST 网络异常不会自动新建付费任务，需人工核实。远程超时不代表平台任务已取消，可能仍扣费。

## 测试

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/smoke.py --base-url http://127.0.0.1:8000
```

第二条需要另一个终端启动 Mock 服务。它首先检查 /health，非 Mock 模式会拒绝提交。

## 正式部署迁移

此版本面向本机/可信局域网开发，尚无登录、任务所有权、用户配额和访问鉴权；不可直接向公网开放付费任务接口。部署时加 HTTPS 反向代理、身份验证、每用户速率/并发/存储配额及上传总量限制，限制请求并发以控制 multipart 缓冲峰值。图片和模型需要明确保留期限及清理策略。

MVP HTTP 进程内 worker 不适用于多进程/多机器。生产将任务放入 Redis + Celery/RQ 等持久队列，增加原子认领、租约、重试和幂等键；使用 PostgreSQL 记录元信息，将图片与 GLB 转移到对象存储并签发受控访问 URL。保留当前 REST 协议，通过存储接口替换下载实现，避免 APP 依赖本地文件布局。
