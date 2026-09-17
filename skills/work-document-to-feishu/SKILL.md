---
name: work-document-to-feishu
description: 审查并整理工作文档后上传到指定飞书知识库。持久化用户的 space_id 与 node_token；上传前在不更改语义和逻辑的前提下，把文档整理成可供领导或同事审阅的专业方案或报告，检查矛盾，并清理重复与「不要 xxx」。禁止把「目标」「方案」改成「要做什么」。当用户说“上传到知识库”“归档工作文档”“把文档放到飞书 wiki”“审查后上传”“绑定知识库”“保存 space_id/node_token”时使用。不负责知识空间成员管理、云盘目录盘点或在线表格表内操作。
---

# 工作文档上传飞书知识库

先绑定并保存目标知识库，再审查整理文档，最后上传到指定 Wiki 节点下。知识库操作默认 `--as user`。认证、缺 scope 处理遵循 `lark-shared`。

未完成审查、未拿到用户确认前，不要调用任何写入命令。

## 核心约束

- 目标只能是飞书知识库，不是云空间文件夹。没有已保存的 `space_id` 时先绑定知识库，不要退化为 Drive 根目录。
- `space_id` 是数字知识空间 ID；`node_token` 是 Wiki 节点 token。不要把 wiki URL、文档 token、文件夹 token 或知识库名称直接当 `space_id`。
- 绑定顺序固定：先解析并保存 `space_id`，再解析并保存父节点 `node_token`。
- 上传前必须审查：在不更改语义和逻辑的前提下整理文档；检查矛盾；冗余包含重复和「不要 xxx」。审查报告未确认不得上传。
- 整理目标是交出可供领导或同事审阅的方案或报告，使用书面语。禁止把「目标」「方案」「实施步骤」改成「要做什么」「注意什么」；原文若是口语标题，改为书面标题。
- 「注意 / 注意事项」不是必须，不要为审查去补这一节。「不要 xxx」当冗余删除；若只是在说明已有步骤的做法，并进该步骤的正面表述。
- 整理只允许结构调整、书面化标题与用语、术语统一、去重、删除否定句，以及按边界决定表格去留；不得改结论、数据、责任人、时间、因果关系，也不得补充原文没有的事实。
- 同一父节点下的创建/导入/上传必须串行。
- `not_found`、`permission_denied`、`missing scope` 时停止重试；只有 `rate_limit` 或临时网络错误才可有限退避。

## 工作流

```text
读取已保存绑定
    ↓
缺失则绑定 space_id，再绑定 node_token，写入 config
    ↓
收集待上传文档
    ↓
审查：整理 + 矛盾检查 + 冗余检查
    ↓
展示审查报告，等待确认
    ↓
串行上传到已保存父节点下
    ↓
把新建节点的 node_token 写回 config，回传链接清单
```

### 1. 读取知识库绑定

先读 [知识库绑定](references/wiki-target.md)，再读取本 Skill 目录下的 `config/wiki-target.json`。

已绑定且用户未要求改目标：用保存的 `space_id` 和 `default_parent_node_token`，不要再询问。

配置缺失、字段为空、或用户要换知识库/父节点：进入步骤 2。用户本轮给出新 URL 或新节点时，覆盖保存。

### 2. 绑定并保存 space_id 与 node_token

必须按这个顺序，不要先存节点再补空间。

**先保存 `space_id`：**

- 用户给了知识库/页面 URL：`lark-cli wiki +node-get --node-token '<url>' --as user --format json`，读取 `space_id`。
- 用户给了知识库名称：`lark-cli wiki +space-list --as user --page-all --format json`，按 `name` 精确匹配。命中 0 条或超过 1 条时列候选，等用户指定后再保存。
- 用户给了数字 `space_id`：用 `lark-cli wiki spaces get --params '{"space_id":"<id>"}' --as user --format json` 校验。

**再保存父节点 `node_token`：**

- 用户给了页面 URL 或 token：`lark-cli wiki +node-get --node-token '<url或token>' --as user --format json`。
- 校验返回的 `space_id` 必须与已保存空间一致；不一致则停止，不要写入。
- 用户只说“知识库根目录”：`default_parent_node_token` 置空，后续创建时只传 `--space-id`。
- 用户没给节点：列出该空间根节点，等用户选定后再保存。

```bash
lark-cli wiki +node-list --space-id <SPACE_ID> --as user --format json
```

写入 `config/wiki-target.json` 后再进入审查。模板见 `config/wiki-target.example.json`。

### 3. 收集文档

记录来源路径、标题、类型、是否可提取正文。会话中直接给出的文稿视为待审查文档，先落到本地工作副本再处理。

### 4. 上传前审查

完整读取 [文档审查](references/doc-review.md)，对每份可提取正文的文档执行：

1. **整理**：整理成可供审阅的方案或报告；沿用或规范书面标题，不改成「要做什么」。语义、逻辑、事实保持不变。涉及表格时按 [文档审查](references/doc-review.md) 的「表格使用边界」：查/比才用表，走/论不用表；对照允许 2 行；属性卡用长表；阶段信息默认有序列表。
2. **矛盾检查**：数字、日期、版本、状态、责任人、结论是否前后冲突。
3. **冗余检查**：重复；以及「不要 / 禁止 / 切勿 / 严禁 xxx」——默认删除，不改写成注意事项。

产出审查报告：整理摘要、矛盾清单、冗余清单、是否建议上传。有未解决矛盾时默认不上传，先交给用户裁决。

用户确认整理稿和上传目标后，才进入步骤 5。用户说“审查后直接上传”视为本轮已授权，仍要先完成审查并展示报告。

无法提取正文的 PDF/图片/压缩包：不做语义整理，只检查文件名、类型、大小和是否误传；发现疑问同样先报告。

### 5. 上传到已保存节点下

完整读取 [上传分流](references/upload-routing.md)。默认挂到 `default_parent_node_token` 下；该字段为空则挂到该 `space_id` 根目录。

| 来源 | 路径 |
|---|---|
| 会话文稿 / `.md` / `.txt` | 审查后 `wiki +node-create`，再用 `docs +update` 写入整理稿 |
| `.docx` / `.doc` / `.html` | 能提取正文则先审查；导入为 `docx` 后 `wiki +move` 迁入 |
| `.xlsx` / `.xls` / `.csv` / `.pptx` | `drive +import` 后 `wiki +move` 迁入 |
| `.pdf` / 图片 / 其他附件 | `drive +upload --wiki-token <父节点>` |

Wiki 命令带 `--as user`。创建节点必须带已保存的 `--space-id`；有父节点时同时带 `--parent-node-token`。

同一父节点下串行执行。成功后把新建节点的 `node_token`、`obj_token`、标题写回 `config/wiki-target.json` 的 `nodes`。

### 6. 回传结果

按 [结果清单](references/result-template.md) 输出：知识库、父节点、每份文档的审查结论、Wiki 链接、`node_token`，以及未上传项和原因。

## 不在范围

- 知识空间成员管理、删除空间、跨库整理方案 → `lark-wiki` / `lark-drive` 对应 workflow
- 已有在线文档的局部精修、评论 → `lark-doc` / `lark-drive`
- 表格或 Base 表内数据操作 → `lark-sheets` / `lark-base`
- 上传到云空间文件夹或“我的空间”根目录，且用户未要求知识库

## 命令速查

```bash
# 绑定：解析节点所属空间
lark-cli wiki +node-get --node-token '<url或token>' --as user --format json

# 绑定：按名称找知识空间
lark-cli wiki +space-list --as user --page-all --format json

# 绑定：列出空间根节点
lark-cli wiki +node-list --space-id <SPACE_ID> --as user --format json

# 上传：在已保存父节点下建文档节点
lark-cli wiki +node-create --space-id <SPACE_ID> --parent-node-token <NODE_TOKEN> --title '<标题>' --as user

# 上传：附件挂到 Wiki 节点下
lark-cli drive +upload --file ./a.pdf --wiki-token <NODE_TOKEN> --as user

# 上传：Drive 文档迁入知识库
lark-cli wiki +move --obj-type docx --obj-token <OBJ_TOKEN> --target-space-id <SPACE_ID> --target-parent-token <NODE_TOKEN> --as user
```
