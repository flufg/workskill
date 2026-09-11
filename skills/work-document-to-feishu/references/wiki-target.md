# 知识库绑定

持久化用户指定的飞书知识库，供后续上传复用。配置文件位于本 Skill 目录：

```text
config/wiki-target.json
```

首次绑定前先复制 `config/wiki-target.example.json`。不要把 wiki URL、文档 token、Drive 文件夹 token 或知识库名称写成 `space_id`。真实 `space_id` 与 `node_token` 只写入本地 `wiki-target.json`，不得提交到本仓库。

## 字段

| 字段 | 含义 |
|---|---|
| `space_id` | 数字知识空间 ID |
| `space_name` | 校验时记下的空间名称，便于人读 |
| `default_parent_node_token` | 默认上传父节点。空字符串表示空间根目录 |
| `default_parent_title` | 父节点标题 |
| `nodes` | 本 Skill 创建或上传成功后追加的子节点记录 |

`nodes[]` 至少保存 `title`、`node_token`、`obj_token`、`obj_type`、`source_path`、`updated_at`。

## 读取规则

1. 文件不存在、JSON 无效、或 `space_id` 为空：视为未绑定，进入绑定流程。
2. `space_id` 已有、`default_parent_node_token` 为空：已绑定到空间根目录，不要再问父节点，除非用户本轮指定了页面。
3. 两者都有：用保存值；用户本轮给出新 URL/名称时覆盖。
4. 写入前用 `wiki +node-get` 或 `wiki spaces get` 校验，不保存未校验的值。

## 绑定顺序

必须先 `space_id`，再 `node_token`。

### 1. 解析 space_id

**有 URL 或 token：**

```bash
lark-cli wiki +node-get --node-token '<url或token>' --as user --format json
```

读取 `data.space_id` 或顶层 `space_id`。同时可得到 `node_token` 和 `title`，但先只把空间写入配置，确认父节点后再写 `default_parent_node_token`。

**只有知识库名称：**

```bash
lark-cli wiki +space-list --as user --page-all --format json
```

按 `name` 精确匹配。0 条：询问是否拼写错误或无权限，不要改名重试。多条：列出 `name` + `space_id` + `space_type`，等用户选定。

**用户直接给了数字 ID：**

```bash
lark-cli wiki spaces get --params '{"space_id":"<SPACE_ID>"}' --as user --format json
```

失败则停止，不要把未校验 ID 写入配置。

`我的文档库` / `个人知识库` / `my_library` 先解析真实 `space_id` 再保存，配置里不写字面量 `my_library`。

```bash
lark-cli wiki spaces get --params '{"space_id":"my_library"}' --as user --format json
```

### 2. 解析并保存 node_token

空间已保存后，再确定默认父节点。

- 用户给了页面 URL/token：再次 `wiki +node-get`。返回的 `space_id` 必须等于已保存 `space_id`，否则停止。
- 用户说上传到知识库根目录：`default_parent_node_token` 设为 `""`。
- 用户没给节点：列出根节点供选择。

```bash
lark-cli wiki +node-list --space-id <SPACE_ID> --as user --format json
```

需要子节点时：

```bash
lark-cli wiki +node-list --space-id <SPACE_ID> --parent-node-token <PARENT> --as user --format json
```

`--space-id` 必须是数字 ID。`--parent-node-token` 必须是 wiki node token；用户给的是 docx URL 时，先 `wiki +node-get` 取出 `node_token`。

## 写入配置

校验通过后覆盖写入 `config/wiki-target.json`。保留已有 `nodes`，除非用户要求换知识库或清空历史。

换知识库时：更新 `space_id` / `space_name`，清空 `default_parent_*` 和 `nodes`，再重新绑定父节点。

上传成功后追加 `nodes`，不要用新节点覆盖 `default_parent_node_token`，除非用户明确把该节点设为新的默认父节点。

## 失败停止

| 情况 | 动作 |
|---|---|
| `not_found` / `permission_denied` / `missing scope` | 停止，报告缺权限或链接无效 |
| 父节点不属于已保存空间 | 停止，不写入 |
| 名称匹配 0 条或多条未选定 | 停止询问，不猜测 |
| 配置写盘失败 | 本轮仍可用内存中的绑定完成上传，并明确告知未持久化 |
