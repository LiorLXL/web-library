# Zotero Translators 调研与导入导出 v1 路线

本文档记录 Zotero translators 的用途、输入输出和本项目的可复用边界。它是后续实现“添加条目 / 引用文本导入 / 元数据检索 / 引用导出”的约束文件之一。

## 基本结论

Zotero translators 是 Zotero 官方运行时中的 JavaScript 转换器。它们不是普通浏览器脚本，也不是可以直接在 Python 后端执行的模块。

本项目 v1 不直接执行 Zotero translator JS，而是参考其中的识别规则、API 地址和字段映射，用 Python 自己查询公共 API 或解析导入文本，再写入本地副本 `zotero.sqlite` 的原生表结构。

## Translator 类型

### Search translator

Search translator 用于“给一个标识符或检索项，返回 Zotero 条目元数据”。

典型输入是 DOI、ISBN、ADS Bibcode 等强标识符。典型输出是一个或多个 Zotero item 字段，然后由 Zotero runtime 调用 `item.complete()` 完成导入。

本项目 v1 对应功能是“标识符导入”。

### Web + Search translator

Web + Search translator 同时支持网页识别和搜索。网页识别通常依赖浏览器中的页面 DOM、URL、cookies 或站点页面结构；搜索部分则可能只需要一个 ID 和公共 API。

例如 PubMed 和 arXiv 都有 `doSearch(item)` 路线，可以绕开前台浏览器页面抓取，直接查询官方 API。

本项目 v1 只参考其中的搜索/API 部分，不实现 `doWeb(doc, url)`，不做网页 DOM 抓取。

### Import translator

Import translator 用于“把引用文本或引用文件转换成 Zotero 条目”，例如 RIS、BibTeX、CSL JSON、PubMed XML、MARCXML。

Import translator 不是标识符检索。它的输入是已经拿到的引用文本/文件内容，输出是条目元数据。

本项目 v1 对应功能是“引用文本导入”。

### Export translator

Export translator 用于“把 Zotero 条目导出为某种文件格式”，例如 BibLaTeX、CSV、RDF、TEI、CFF、Note Markdown。

本项目 v1 对应功能是“引用导出”。由于 Zotero translator JS 依赖 Zotero runtime，本项目不直接执行这些 JS，而是参考其字段映射和格式习惯，用 Python 生成导出文件。

## 本机 translators 调查

本机路径：

```text
C:\Users\27216\Zotero\translators
```

调查到 `.js` translators 共 838 个。按 `translatorType` 粗略统计：

| translatorType | 数量 | 含义 |
| --- | ---: | --- |
| 1 | 16 | Import |
| 2 | 12 | Export |
| 3 | 10 | Import + Export |
| 4 | 721 | Web |
| 6 | 1 | 组合类型 |
| 8 | 8 | Search |
| 12 | 8 | Web + Search |

### Search translator 清单

| 文件 | 主要用途 | v1 处理 |
| --- | --- | --- |
| `ADS Bibcode.js` | ADS Bibcode / DOI 查询，内部走 ADS API 与 RIS 导入 | v1 做识别与去重；无 token 时不创建半成品 |
| `BnF ISBN.js` | 法国国家图书馆 ISBN 查询 | ISBN fallback 参考 |
| `Camara Brasileira do Livro ISBN.js` | 巴西 ISBN 查询 | ISBN fallback 参考 |
| `Crossref REST.js` | DOI / bibliographic query，经 Crossref REST API | v1 DOI 主路线 |
| `DOI Content Negotiation.js` | DOI.org 内容协商，分流 Crossref / DataCite / CSL JSON | v1 DOI fallback 参考 |
| `K10plus ISBN.js` | ISBN / query，经 SRU/MARCXML | ISBN fallback 参考 |
| `LIBRIS ISBN.js` | ISBN，经 LIBRIS | ISBN fallback 参考 |
| `National Library of Poland ISBN.js` | 波兰图书馆 ISBN/MARCXML | ISBN fallback 参考 |

### Web + Search translator 清单

| 文件 | 主要用途 | v1 处理 |
| --- | --- | --- |
| `arXiv.org.js` | arXiv 页面识别与 arXiv API 搜索 | v1 用 arXiv API |
| `PubMed.js` | PubMed 页面识别与 eUtils 搜索 | v1 用 PubMed eUtils XML |
| `OpenAlex.js` | OpenAlex ID/页面 | 后续 |
| `ERIC.js` | ERIC Number/页面 | 后续 |
| `Open WorldCat.js` | ISBN/OCLC/页面 | ISBN fallback 参考 |
| `CCPINFO.js` | ISBN/页面 | 后续 |
| `WHO.js` | ISBN/页面 | 后续 |
| `Yiigle.js` | DOI/页面 | 后续 |

### Import translator 清单重点

严格 Import 类型中包含 `PubMed XML`、`Crossref Unixref XML`、`Datacite JSON`、`OpenAlex JSON`、`MARCXML`、`MARC`、`MEDLINE/nbib` 等。

同时有一些 `Import + Export` 类型非常重要：

| 文件 | 用途 | v1 处理 |
| --- | --- | --- |
| `RIS.js` | RIS 引用文本导入/导出 | v1 轻量解析 |
| `BibTeX.js` | BibTeX 导入/导出 | v1 轻量解析 |
| `CSL JSON.js` | CSL JSON 导入/导出 | v1 标准 JSON 解析 |
| `PubMed XML.js` | PubMed XML 导入 | v1 XML 解析 |

### Export translator 清单

本机纯 Export translator 当前查到 12 个：

| 文件 | 用途 | v1 处理 |
| --- | --- | --- |
| `BibLaTeX.js` | BibLaTeX 引用导出 | v1 支持轻量导出 |
| `CSV.js` | CSV 元数据导出，适合表格软件 | v1 支持轻量导出 |
| `Zotero RDF.js` | Zotero RDF，包含集合、笔记、附件等复杂结构 | 后续高级格式 |
| `Unqualified Dublin Core RDF.js` | Dublin Core RDF | 后续高级格式 |
| `TEI.js` | TEI XML | 后续高级格式 |
| `CFF.js` | Citation File Format | 后续高级格式 |
| `CFF References.js` | CFF references | 后续高级格式 |
| `Note HTML.js` | 笔记 HTML 导出 | 后续笔记功能 |
| `Note Markdown.js` | 笔记 Markdown 导出 | 后续笔记功能 |
| `Simple Evernote Export.js` | Evernote ENEX | 后续高级格式 |
| `Wikidata QuickStatements.js` | Wikidata QuickStatements | 后续高级格式 |
| `Wikipedia Citation Templates.js` | Wikipedia 引用模板 | 后续高级格式 |

另外，常用的 `BibTeX.js`、`RIS.js`、`CSL JSON.js` 是 `translatorType = 3`，属于 Import + Export。它们虽然不是纯 Export translator，但非常适合本项目引用导出 v1。

## 添加条目 v1 覆盖范围

### 标识符导入

v1 支持识别：

- DOI
- PMID
- arXiv ID
- ADS Bibcode
- ISBN

v1 查询路线：

- DOI：优先 Crossref REST API，必要时后续补 DOI Content Negotiation fallback。
- PMID：PubMed eUtils `efetch` XML。
- arXiv ID：arXiv Atom API。
- ADS Bibcode：当前先支持识别和去重；无 ADS API token 时不创建半成品。
- ISBN：优先 OpenLibrary ISBN API，后续可补 WorldCat、BnF、K10plus、LIBRIS 等 fallback。

### 引用文本导入

v1 支持：

- 自动识别
- RIS
- BibTeX
- CSL JSON
- PubMed XML

引用文本导入和标识符导入都输出统一 metadata，再进入同一套自动去重和 Zotero SQLite 写入流程。

## 引用导出 v1 覆盖范围

v1 支持导出已勾选条目，格式包括：

- BibTeX
- BibLaTeX
- RIS
- CSL JSON
- CSV

导出规则：

- 导出只读当前后端状态，不写 Zotero SQLite，不写 app journal。
- 不直接执行 Zotero translator JS。
- 不导出附件文件数据，不打包 PDF，不导出笔记全文。
- 不实现 RDF、TEI、CFF、Note HTML/Markdown、Evernote、Wikidata、Wikipedia Citation Templates 等高级格式。
- BibTeX 和 BibLaTeX citekey 参考 Zotero 默认 `%a_%t_%y` 思路，导出批次内保证唯一。
- CSV 使用 UTF-8 BOM，方便 Excel 打开中文。

## 自动去重规则

所有导入都必须先去重再创建。

强标识符优先级：

- DOI：忽略大小写，去掉 `doi:`、`https://doi.org/`、`https://dx.doi.org/` 前缀。
- PMID / PMCID：按规范化 ID 比较。
- arXiv ID：去掉 `arXiv:`、URL 包装和版本号，例如 `v2`。
- ADS Bibcode：按完整 bibcode 比较。
- ISBN：去掉空格和连字符，并把 ISBN-10 规范化为 ISBN-13。

只用强标识符自动去重，不用标题相似度自动合并，避免误合并。

命中一个已有条目时：

- 不创建新条目。
- 不覆盖已有字段。
- 如果当前选中真实文件夹，则把已有条目加入该文件夹。
- 返回已有条目 key，前端定位到已有条目。

命中多个已有条目时：

- 返回冲突候选。
- 不创建新条目。
- 让用户后续进入候选条目查看或手动处理。

未命中重复时才创建新条目。

## 写回 Zotero SQLite 的边界

新条目只写 Zotero 原生结构：

- `items`
- `itemData`
- `itemDataValues`
- `creators`
- `itemCreators`
- `tags`
- `itemTags`
- `collectionItems`

必须遵守：

- 不修改 Zotero 原生 schema。
- 不新增 `fields.fieldName`。
- 字段写回只允许写 `fields` 表中已经存在的字段名。
- 新条目设置 `synced = 0`。
- 写入 app journal，保证本地副本后续同步流程可追踪。

## 后续扩展建议

- DOI 增加 DataCite 和 DOI Content Negotiation fallback。
- ISBN 增加多源级联和 MARCXML 解析。
- ADS Bibcode 支持用户配置 ADS API token。
- Import parser 后续可替换为更完整的解析库，但仍保持统一 metadata 输出。
- 添加附件、PDF 下载、网页快照应拆成独立功能，不混入 v1 条目元数据导入。
