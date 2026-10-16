# 用 GitHub Pages 照片进行多视图测试

现在推荐直接从电脑选图并自动发布，见 [实时上传配置](GITHUB_AUTO_UPLOAD.md)。下文保留手动发布与图片链接模式。

方案：GitHub Pages 托管公开照片；电脑上的 Python 后端保留 Key、调用混元并保存 GLB。无需先把后端部署到公网，也无需配置 HUNYUAN_IMAGE_BASE_URL。测试页仍打开 http://127.0.0.1:8000/docs。

## 一次性开通 Pages

1. 在 GitHub 创建用于公开测试照片的仓库，例如 craft-photos。GitHub Free 使用公开仓库；已有可用 Pages 仓库也可以。
2. 将项目根目录 github-pages-images 的内容上传至这个仓库根目录。模板不含实际照片；将同一件作品的前、后、左、右、上、下照片放入 images 文件夹，命名为 front.jpg、back.jpg、left.jpg、right.jpg、top.jpg、bottom.jpg。不要上传整个 Unity 项目或后端密钥。
3. 在照片仓库 Settings → Pages 中，选择 Deploy from a branch，分支 main，目录 / (root)，保存。如果仓库默认分支不是 main，选择实际分支。
4. 等待 Pages 发布，使用该设置页面的 Visit site 打开真正的网站地址。常见形式是 https://用户名.github.io/craft-photos/；此地址仅为形式示例，不代表已经发布。
5. 打开首页列出的六张照片链接，确认显示图片。图片地址形如 https://用户名.github.io/craft-photos/images/front.jpg。github.com 的仓库文件页面不是图片直链。

用户已在 ModelPreview 仓库启用 Pages 并上传照片。当前发布目录位于仓库根目录的 github-pages-images，实际照片以用户提交为准。初始发布 ZIP 只含模板与目录规则，不含实际作品照片。

如果在现有 Unity 仓库中发布，根目录的 .gitattributes 可能把 JPG/PNG 全部交给 Git LFS。发布模板的 images/.gitattributes 已针对该文件夹禁用 LFS，必须一并提交。已有 LFS 图片需要先执行 `git add github-pages-images/images`，再执行 `git add --renormalize github-pages-images/images`，然后提交、推送。GitHub Pages 不支持 LFS 图片；网页返回 131 字节的指针文本时，即使 HTTP 200 也不能显示照片。

使用本项目现有仓库并从根目录发布时，图片目录是 `https://zhang5120240703.github.io/ModelPreview/github-pages-images/images/`。如果把发布目录放进 docs 子目录，且 Pages 仍从仓库根目录发布，网址也必须包含 `/docs/`。文件名区分大小写，底面统一为 bottom.jpg。

## 本地填写链接并测试

启动/重启本地后端，打开中文测试台，在“照片来源”中选择“使用 GitHub Pages 图片链接”。

将首页显示的 images/ 目录地址粘贴到“图片目录地址”，点击“按六个面填写 .jpg 链接”；也可逐个填写正面、背面、左侧、右侧、顶面、底面的链接。只要求正面必填，其余可留空。若照片是 PNG，保留 .png 并修改相应链接，不要直接把文件改名为 .jpg。

先点击“检查图片链接（不生成）”：后端从 Pages 下载图片，校验 HTTP 状态、文件大小、真实格式和像素，不向混元提交任务。检查通过只证明本机可读取，不保证腾讯网络也能读取。

准备好后，手动点击“使用图片链接开始生成（计费）”。后端再次校验照片，通过后才创建任务；将原始 Pages 图片 URL 传给腾讯，正面对应 image_url，其余五面对应 multi_view_images。原有任务查询、GLB 下载和 Unity 加载流程保持不变。

当前入口仅接受 https://用户名.github.io/... 下的 JPG/PNG 直链，不接受自定义域名、仓库网页、登录页面、重定向或 localhost。每张最多 4 MiB，宽高均为 129–4999 像素。不需要把 Key 填进网页或推送到 GitHub。

这是一种固定照片的测试方式。更换作品时先上传新照片并等待发布，建议使用独立作品目录，例如 images/basket-01/，避免 CDN 缓存或正在运行的任务读到被替换的照片。生成期间保持图片可访问。

## 接口

`POST /api/v1/image-links/check`：仅检查，不生成。

`POST /api/v1/reconstructions/from-urls`：检查并创建真实混元任务，成功返回 202 和原有任务响应。

两者均接收 JSON：

```json
{
  "image_urls": [
    "https://你的用户名.github.io/craft-photos/images/front.jpg",
    "https://你的用户名.github.io/craft-photos/images/top.jpg"
  ],
  "views": ["front", "top"]
}
```

1–6 个 URL。省略 views 时默认按 front/back/left/right/top/bottom；显式传入时必须一一对应、不重复且包含 front。检查接口不要求已配置混元 Key；创建接口要求 Key，且两者仅用于 provider=hunyuan。

参考：[GitHub Pages 官方创建说明](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)、[混元多视图接口](https://cloud.tencent.com/document/product/1823/137181)。
