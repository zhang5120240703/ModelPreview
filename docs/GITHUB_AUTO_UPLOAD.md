# 从电脑选图并自动上传 GitHub

现在可以直接在本地中文测试页选择 1–6 张照片、标记视角、点击“上传并开始生成”。后端自动执行：保存照片 → 一次 GitHub 提交上传整组照片 → 等待 Pages 可读取并核对文件 → 提交混元 → 下载 GLB。无需手动复制链接或改照片名。

照片会公开发布到配置的照片仓库。每次任务使用独立目录，例如 `github-pages-images/uploads/任务编号/front.jpg`，保留原始 JPG/PNG 格式；原文件名不发布。该目录附带取消 LFS 的规则，GitHub API 上传的也是实际图片字节，不是 LFS 指针。

## 一次性配置

本项目当前的 Pages 地址为 `https://zhang5120240703.github.io/ModelPreview`，发布分支 main，发布目录为仓库根目录。默认上传到同一仓库中的 github-pages-images/uploads。也可以使用专门的公开照片仓库，但要填写它实际的 Pages 地址和发布分支。

1. 打开 [GitHub 新建细粒度 Token 页面](https://github.com/settings/personal-access-tokens/new)。Token 名称可填 ModelPreview Photos；设置有效期。
2. Repository access 选择 **Only select repositories**，选中要存照片的仓库，例如 ModelPreview。
3. Repository permissions 中将 **Contents** 设为 **Read and write**。无需申请 Workflows 写入权限，本功能不修改工作流。生成并复制 Token。
4. 在本项目根目录 PowerShell 运行：

```powershell
.\scripts\configure-github.ps1
```

按提示核对仓库、Pages 网站根地址、发布分支和仓库内图片目录。当前 ModelPreview 可以使用默认值，按回车确认。最后粘贴 GitHub Token，输入不回显。脚本只更新被 Git 忽略的 backend/.env，保留原有混元 Key，不提交照片或建模任务。不要把 Token 发到聊天或填进测试网页。

5. 如果后端正在运行，在其终端按 Ctrl+C 停止，再运行：

```powershell
.\scripts\start-backend.ps1
```

配置变量参考 backend/.env.github.example；它是追加配置示例，不要覆盖现有的 HUNYUAN_API_KEY。环境变量优先于 .env。

## 使用与等待

刷新 [本地中文测试页](http://127.0.0.1:8000/docs)，选择“从电脑选择照片（自动上传 GitHub）”。选择同一物体的照片，逐张确认前、后、左、右、上、下；至少包含一张正面，视角不能重复，不要求凑满六张。每张最多 4 MiB，宽高均为 129–4999 像素。

页面会依次显示“正在上传照片到 GitHub”“等待图片发布”“正在提交建模任务”“正在生成模型”“正在下载模型”。GitHub 图片发布阶段尚未提交混元，发布失败或超时不会调用付费建模。默认最长等待 Pages 20 分钟；GitHub 官方说明发布更新可能需要最多约 10 分钟，实际以部署和图片可读状态为准。

每轮读取会核对公网图片与本地照片的 SHA-256，确认是这次上传的实际内容后才提交混元。没有真实生成进度时 progress=null；不编造百分比。浏览器等待上限包含图片发布和建模时间，关闭页面或停止等待不会取消后端任务，之后可用原任务编号继续查询。

“完成”表示平台返回了可下载的模型文件，不表示还原质量合格。背景简洁、主图清晰、无手部遮挡、视角一致仍然很重要；上传方式不会自动修复这些输入问题。

## 恢复与常见错误

- 后端在上传/等待 Pages 阶段重启：按本地 manifest 继续处理，已确认的 GitHub 提交不重传；原任务不变。
- 提交混元时中断且未保存云端编号：保持防重复付费策略，标记失败并要求先核实平台记录，不自动重提。
- 已保存混元编号：重启后继续查询原云端任务，不重新发布照片或创建建模任务。
- Token 无效、仓库未授权、分支保护拒绝或频率限制：任务错误显示中文原因，GitHub 阶段失败时尚未提交混元。检查仓库的 Contents 写入权限和所选分支。
- 图片一直 404：核对 Pages 发布分支及源目录。仓库路径与公开 URL 必须对应；从 /docs 发布时上传目录也必须位于 docs 下。
- 公网返回 LFS 指针或内容不一致：在调用混元前失败，保留原始照片与任务记录用于核对。

自动上传会在远程照片仓库新增提交。以后从本地推送同一仓库前，需要先同步远程新增的照片提交。当前没有自动删除公开照片，任务目录会保留。

## 验证边界

自动化测试使用模拟 GitHub API、Pages 图片和混元响应，覆盖单次提交、基于现有树追加文件、非强制分支更新、并发提交冲突、丢失响应恢复、Pages 等待、图片一致性、发布超时不扣建模额度、等待阶段重启和完整任务流程。未使用真实 GitHub Token 发布照片，也未新建真实混元任务；配置真实 Token 后仍需首次手动联调。

官方参考：[GitHub Token 创建](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)、[Git 对象 API](https://docs.github.com/en/rest/git)、[Pages 创建与发布](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)。
