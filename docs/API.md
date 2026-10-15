# APP 接入 API v1

后端独立于 Android 原生、Flutter、uni-app 和 Unity。中文测试台：`GET /docs`；机器可读协议：`GET /openapi.json`；原生 Swagger 技术文档保留于 `GET /docs/swagger`。所有路径相对于部署地址。当前开发版无鉴权，生产需补身份/任务所有权。Key 不属于客户端协议。

中文测试台可直接选图、上传、等待结果、查询既有任务、复制编号和模型地址或下载 GLB。页面每 3 秒查询一次，等待上限 1900 秒；停止等待不会取消后端任务。界面显示“排队中 / 正在生成模型 / 模型已生成 / 模型生成失败”，REST 字段和状态代码仍沿用下面的协议。

## 创建任务

`POST /api/v1/reconstructions`，`multipart/form-data`，**重复的 images 字段**。混元和 Mock 支持 1–6 张，Meshy 支持 1–4 张，fal_tripo 支持 2–4 张。支持可选的重复 `views` 字段，与照片一一对应；六面为 front（正面）、back（背面）、left（左侧）、right（右侧）、top（顶面）、bottom（底面），不重复且包含 front，省略时依此顺序排列。最多四张的 Provider 不接受 top/bottom 标注。不接受本地路径、第三方 URL 或其他字段。JPG/JPEG 配 `image/jpeg`，PNG 配 `image/png`；通用默认每张 10 MiB，解码后最多 2400 万像素，扩展名必须和真实内容一致。推荐相同物体、同一光照。

腾讯混元（provider=hunyuan）接入限制每张最多 4 MiB、宽高均为 129–4999 像素。单图可在本地直接测试；2–6 张图需先配置云端能读取的公网 HTTPS 图片入口，否则在创建云端任务前返回 422。前端可通过 `/health` 获得限制及配置状态。视角字段目前用于混元，其他 Provider 保持自身图片顺序约定。

固定照片可另用 GitHub Pages 图片直链：`POST /api/v1/image-links/check` 只检查链接；`POST /api/v1/reconstructions/from-urls` 接收 `{image_urls:[...],views:[...]}` 检查并创建混元任务，无需配置本机公网入口。图片限 HTTPS 的 *.github.io 直链，不跟随重定向，检查失败不创建任务。详见 [GitHub Pages 图片接入](GITHUB_PAGES_IMAGES.md)。原 multipart 接口不接受 URL 字段。

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/reconstructions -F "images=@front.jpg" -F "images=@back.jpg" -F "views=front" -F "views=back"
```

成功 `202 Accepted`，示例：

```json
{"task_id":"54d1d0340e0f4118983b6a111544b86e","status":"queued","progress":null,"model_url":null,"error":null,"provider":"mock","is_mock":true,"status_url":"/api/v1/reconstructions/54d1d0340e0f4118983b6a111544b86e"}
```

task_id 是不透明字符串，不要在客户端推断结构。status_url 是相对路径，用当前 API 根地址解析。上传顺序保持；Meshy 的首图用作主要正面参考。禁止静默重试创建请求，以免创建多个计费任务。

## 查询任务

`GET /api/v1/reconstructions/{task_id}`，成功 200：

```json
{"task_id":"54d1d0340e0f4118983b6a111544b86e","status":"succeeded","progress":100,"model_url":"http://192.168.1.20:8000/api/v1/models/54d1d0340e0f4118983b6a111544b86e/file","error":null,"provider":"mock","is_mock":true,"status_url":"/api/v1/reconstructions/54d1d0340e0f4118983b6a111544b86e"}
```

| 字段 | 约定 |
| --- | --- |
| status | queued / processing / succeeded / failed |
| progress | 0–100 或 null。null 时显示等待动画，不制造百分比 |
| model_url | succeeded 后的绝对 URL，其他状态 null；下载来自可配置 PUBLIC_BASE_URL |
| error | failed 后的原因文本，其他状态 null |
| provider / is_mock | 标明是否为模拟结果；客户端必须保留 Mock 提示 |

每 3–5 秒轮询一次，成功/失败后停止，APP 进入后台时暂停。网络错误显示可重试状态；不自动重新上传。Unity 等待上限 1900 秒，超时后可以用原 task_id 继续跟踪。

## 下载模型

`GET /api/v1/models/{task_id}/file`，成功 200，`Content-Type: model/gltf-binary`，带下载文件名。返回自包含 GLB 2.0，标准材质和嵌入纹理，由 Unity glTFast 或其他兼容查看器读取。客户端应设置下载超时/体积上限，并考虑解码后内存通常高于文件体积。

## 错误

HTTP 错误主体通常为 `{"detail":"说明"}`；参数结构错误也可能是 FastAPI 标准 detail 数组。第三方任务执行失败通过 GET 200 + status=failed + error 返回。

| HTTP | 情况 |
| --- | --- |
| 400 | multipart 非法、超过文件数、存在额外表单字段 |
| 413 | 单文件或总请求超过限制 |
| 415 | 不支持类型、伪造扩展名、损坏或超像素图片 |
| 422 | 缺 images、数量不符或路由参数错误 |
| 503 | 混元或 fal Provider 缺少本地密钥，未创建云端任务 |
| 404 | 任务不存在或成功任务文件缺失 |
| 409 | 模型尚未成功生成，包括失败任务 |

`GET /health`：返回 `status`、`provider`、`provider_ready`、`min_images`、`max_images`、`max_image_mb`、`image_order`，以及混元的 `model`、`enable_pbr`、`face_count`、`public_images_configured`、`public_image_links_supported`。密钥不返回；`provider_ready` 仅表示本地已填写，未向腾讯校验有效性。`public_images_configured` 仅表示本机临时图片入口 URL 形式符合公网 HTTPS 要求，不证明外网可达；它为 false 时仍可通过独立的 from-urls 接口使用 Pages 照片。该接口不代表云平台连通或余额足够。

混元多图内部使用 `GET /api/v1/reconstructions/{task_id}/images/{image_index}?token=...` 提供临时原图。服务端创建不可猜测的任务令牌，任务结束或过期后失效；客户端无需调用或构造此地址。

## 网络地址

Editor：127.0.0.1。Android 官方模拟器：10.0.2.2。真机：电脑局域网 IP；电脑服务绑定 0.0.0.0，放行 TCP 8000，手机和电脑同网。**PUBLIC_BASE_URL 和 Unity 中的“后端服务地址”必须同时改为客户端可达地址。** model_url 是服务器配置，不能仅改 Unity 输入框。0.0.0.0 是监听地址，不是客户端访问地址。正式部署统一使用 HTTPS 域名。
