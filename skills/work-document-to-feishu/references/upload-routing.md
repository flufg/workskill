# 上传分流

审查通过并经用户确认后，把整理稿或附件上传到已保存知识库。身份默认 `--as user`。

父节点取 `config/wiki-target.json` 的 `default_parent_node_token`；为空则挂到该 `space_id` 根目录。不要传到 Drive 文件夹或“我的空间”。

`--wiki-token` 和 `--parent-node-token` 一律传 wiki node token，不是 `space_id`，也不是 docx/sheet 的 `obj_token`。

## 分流表

| 来源 | 默认动作 | 结果 |
|---|---|---|
| 会话文稿、`.md`、`.txt` | 建 Wiki 文档节点并写入整理稿 | 知识库 `docx` 页面 |
| `.html` | 能提取则按文本路径；否则导入为 `docx` 再迁入 | 知识库 `docx` 页面 |
| `.docx` / `.doc` | 审查后：有整理稿则按 Markdown 路径；用户要求保真则导入再迁入 | 知识库 `docx` 页面 |
| `.xlsx` / `.xls` / `.csv` | `drive +import` 为 `sheet`（用户明确要求 Base 时用 `bitable`），再迁入 | 知识库表格节点 |
| `.pptx` | `drive +import --type slides`，再迁入 | 知识库幻灯片节点 |
| `.pdf` / 图片 / 压缩包 / 其他 | `drive +upload --wiki-token` 挂到父节点下 | 父页面下的附件文件 |

同一父节点下的 `node-create` / `import` / `upload` / `move` 必须串行。

## 文本工作文档

整理稿确认后：

```bash
lark-cli wiki +node-create \
  --space-id <SPACE_ID> \
  --parent-node-token <PARENT_NODE_TOKEN> \
  --title '<标题>' \
  --obj-type docx \
  --as user
```

根目录上传时省略 `--parent-node-token`，仍必须传 `--space-id`。

从返回值读取 `node_token`、`obj_token`。写入正文前读取 `lark-doc` 的更新说明，使用整理稿，不要用未审查原文：

```bash
lark-cli docs +update --doc '<OBJ_TOKEN>' --command overwrite --doc-format markdown --as user
```

本地已有确认后的 `.md` 文件时，按 `lark-doc` 要求从文件读入内容。写入失败且节点已创建：向用户报告空节点 `node_token`，不要默默删除，除非用户要求回滚。

## 导入后迁入知识库

Word 保真、表格、幻灯片走这条路径。`drive +import` 的目标是临时 Drive 位置，导入成功后必须立刻迁入已绑定知识库，不要把文档留在云空间根目录。

```bash
lark-cli drive +import --file ./a.docx --type docx --name '<标题>' --as user
```

成功后取 `obj_token` / `type`，再迁入：

```bash
lark-cli wiki +move \
  --obj-type docx \
  --obj-token <OBJ_TOKEN> \
  --target-space-id <SPACE_ID> \
  --target-parent-token <PARENT_NODE_TOKEN> \
  --as user
```

根目录省略 `--target-parent-token`。`obj-type` 与导入结果一致：`docx` / `sheet` / `bitable` / `slides`。

迁入失败时：报告 Drive 文档仍在原处及 token，等待用户决定重试、改挂点或删除临时文档。不要在未确认时删除。

批量导入同一位置必须串行；遇到 `232140101`、`232140100`、`233523001` 时等待后最多重试 3 次。

## 附件上传

```bash
lark-cli drive +upload --file ./a.pdf --wiki-token <PARENT_NODE_TOKEN> --name '<文件名>' --as user
```

父节点为空（空间根目录）时，先在根目录创建一个用于收件的 `docx` 节点或请用户指定页面，再上传附件。不要把附件改传到 Drive 根目录。

`--wiki-token` 与 `--folder-token` 互斥。覆盖已有附件需要用户明确提供已有 `file_token`，并传 `--file-token`。

## 标题

未指定标题时，使用源文件名去掉扩展名，或文稿一级标题。上传前告诉用户将使用的标题。已在 `nodes` 中出现相同标题时，先询问是更新、新建重名页面还是取消。

## 成功后回写

把新建记录追加到 `config/wiki-target.json` 的 `nodes`：

- `title`
- `node_token`
- `obj_token`
- `obj_type`
- `source_path`
- `updated_at`（ISO 8601）

不要用新页面覆盖 `default_parent_node_token`。

## 失败停止

- `not_found` / `permission_denied` / `missing scope`：停止该文件，继续报告其余文件前先说明
- 父节点不属于已保存 `space_id`：停止整批
- 审查未确认或存在未裁决阻断矛盾：不调用写入命令
