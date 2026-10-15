# 六面照片 GitHub Pages 发布目录

把本目录的**内容**上传到照片仓库根目录，而不是整个 Unity 工程。目录结构：

```text
index.html
.nojekyll
images/
  front.jpg
  back.jpg
  left.jpg
  right.jpg
  top.jpg
  bottom.jpg
```

模板不含实际照片，请自行放入希望公开的作品照片。JPG/PNG 均可，PNG 文件保留真实后缀；不要只改后缀伪装格式。每张最多 4 MiB，宽高均须为 129–4999 像素。

仓库 Settings → Pages → Deploy from a branch → main → / (root) → Save。发布成功后打开网站，每张链接须直接显示图片。详细步骤见主项目 docs/GITHUB_PAGES_IMAGES.md。

API Key、backend/.env 和 Unity 源码都不属于此发布目录。此站点仅提供图片，不运行 Python、不直接调用混元。
