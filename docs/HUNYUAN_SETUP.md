# 腾讯官方混元 3D 接入

本项目使用腾讯 TokenHub 的 HY-3D REST API，默认模型 `hy-3d-3.1`。需要 **TokenHub API Key**；腾讯云 CAM 的 SecretId/SecretKey 或 fal Key 不能用于这里。

官方入口：[创建 TokenHub Key](https://console.cloud.tencent.com/tokenhub/apikey?regionId=1)、[密钥文档](https://cloud.tencent.com/document/product/1823/130090)、[HY-3D 接口](https://cloud.tencent.com/document/product/1823/137181)、[计费说明](https://cloud.tencent.com/document/product/1823/130055)。模型及选项可能影响费用，以提交时腾讯控制台规则为准。

## 本地先测试一张照片

在项目根目录的 PowerShell 中执行：

```powershell
./scripts/configure-hunyuan.ps1
```

按提示粘贴 Key，输入不会显示，按回车保存。脚本仅更新本机 `backend/.env` 的 Provider、Key 和默认模型，不提交任务。该文件已被 Git 忽略，仍应按密钥文件保管，勿分享或提交。

如果后端正在运行，先在它的终端按 Ctrl+C 停止，再启动：

```powershell
./scripts/start-backend.ps1
```

打开 [中文测试台](http://127.0.0.1:8000/docs)，确认显示“腾讯官方混元 3D”和“已填写”。这仅代表本地配置存在，不保证 Key 有效或余额足够。选择一张正面 JPG/PNG，宽高都在 129–4999 像素之间，文件不超过 4 MiB，点击“上传并开始生成”。此操作会创建真实付费任务。

后端上传照片、保存腾讯任务编号、持续查询，并在完成后下载 GLB。没有真实数字进度时只显示等待状态。成功后复制任务编号，在 Unity 预览场景填写相同的后端地址，点击“查询并加载”；原有加载流程无需修改。

如需手动配置，可参考 `backend/.env.hunyuan.example`，但不要覆盖已有密钥：

```dotenv
PROVIDER=hunyuan
HUNYUAN_API_KEY=在本机填写你的TokenHub密钥
HUNYUAN_MODEL=hy-3d-3.1
HUNYUAN_ENABLE_PBR=false
PUBLIC_BASE_URL=http://127.0.0.1:8000
```

单图直接发送原始 Base64，不需要公网服务器。默认生成带颜色纹理的 Normal 模型，不开启额外 PBR，不指定面数；结果格式使用官方默认的 OBJ+GLB，系统取 GLB。平台默认网格可能较大，Android 使用前应检查内存、帧率和文件体积；如需指定面数，可设置 `HUNYUAN_FACE_COUNT=30000`，但应先核实对应计费。下载默认上限 64 MiB。

## 2–6 张照片的额外配置

如果暂时只测试固定照片，可以先发布到 **GitHub Pages**，在本地测试台切换“照片来源 → 使用 GitHub Pages 图片链接”，先检查链接，再手动开始生成。此方式无需配置本机公网入口，步骤见 [GitHub Pages 图片接入](GITHUB_PAGES_IMAGES.md)。下面的公网入口方案用于从电脑直接上传多张新照片。

官方附加视角参数只接受公网图片 URL。腾讯无法读取你电脑上的 localhost 地址，因此当前会在提交前拦截未配置公网入口的多图任务。

准备一个可被腾讯访问的 HTTPS 入口，将它的图片路径代理到本机/服务器后端，并设置：

```dotenv
HUNYUAN_IMAGE_BASE_URL=https://你的图片服务域名
```

应开放的图片路径是 `/api/v1/reconstructions/{task_id}/images/{image_index}`，必须原样保留 `token` 查询参数。服务端会自动生成任务专用临时令牌，无需自己填写照片 URL；令牌最长保留到任务超时后 10 分钟，任务成功或失败后立即停止访问。不要在代理访问日志中记录完整 token。当前没有自动配置域名、证书、隧道或对象存储。

当前开发版没有付费任务鉴权。公网入口只代理上述临时图片 GET 路径；不要同时开放创建付费任务的 POST 接口。正式部署需增加账号鉴权、用户配额和任务所有权校验。单图测试不需要这一步。

重启后选择同一件物品的 2–6 张照片，在页面逐张选“正面 / 背面 / 左侧 / 右侧 / 顶面 / 底面”，可覆盖前后左右上下六个面。必须包含一张正面，每个视角只能出现一次；允许照片不足六张。系统根据标注生成 `image_url` 与 `multi_view_images`，顶面传 top，底面传 bottom，无需依赖选图顺序。省略标注时默认按前、后、左、右、上、下排序，原有四面顺序保持兼容。页面显示“公网入口已配置”只验证地址形式，实际可达性仍需部署后验证。

## 常见问题

- 页面提示“未配置密钥”：运行隐藏输入脚本后重启后端；确认使用同一项目的 backend/.env。服务启动时的环境变量会优先于 .env。
- Key 无效或访问被拒绝：确认它属于 TokenHub，并检查模型授权、Key 状态与 IP 白名单。
- 余额/额度不足：在腾讯平台确认对应模型账户与额度；本系统不充值、不自动重提失败任务。
- 超时、提交网络错误或服务重启：先核实腾讯请求记录，避免再次点击上传产生重复费用。已保存远程编号的执行中任务会在重启后继续查询；提交成功但编号尚未落盘的任务不会自动重提。
- 下载域名不在白名单：先核实官方结果 URL，再更新 `HUNYUAN_MODEL_DOWNLOAD_HOSTS` 的精确域名，勿改为任意域名。Key 不发送给模型下载服务器。
- 返回模型超过上限：核实平台原任务结果，调整 `MAX_MODEL_MB`；无需为了下载重新提交建模。
- 切回免费流程：设置 `PROVIDER=mock` 并重启，Mock 不会调用腾讯，生成的是测试立方体。

当前已通过 68 项后端自动化测试，其中混元与 Pages 下载使用模拟响应。六图实际建模、多图公网访问和真实模型的 Unity 表现仍需手动联调确认。
