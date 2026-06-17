# Web Library

这是一个面向 Zotero 本地文库的网页端浏览与编辑工具。

项目与 Guangming AI Workbench 分离维护，重点是把本地 Zotero 文库以三栏高密度界面呈现出来，并在不破坏原始数据结构的前提下，提供标签语义解析、结构化字段提取、本地副本编辑等能力。

![image-20260616143947757](assets/image-20260616143947757.png)

![image-20260616144115054](assets/image-20260616144115054.png)

![image-20260616144151252](assets/image-20260616144151252.png)

## 当前功能

- 三栏 Zotero 风格界面：左侧文件夹树与筛选，中间条目表，右侧条目详情。
- 支持文件夹树浏览，以及评分、类型、`#标签`、期刊/会议等级、阅读状态、普通标签筛选。
- 表格字段列可配置，可调整列顺序、列宽，并保留用户设置。
- 支持条目多选；切换筛选条件或文件夹后，已勾选状态仍会保留。
- 支持批量条目管理：删除条目、移入回收站、永久删除、移动到目标文件夹。
- 标题列支持中文条目类型徽标，类型 key 以 Zotero 官方类型定义为准。
- 支持条目前端语义标签解析：
  - `#标签`
  - 阅读状态
  - 评分
  - 期刊/会议等级
- 支持文库级共享快捷标签，用于快速给条目设置 `#标签`。
- 支持结构化字段提取与写回：
  - `remark`
  - `title_zh`
  - `abstract_zh`
- 支持在表格单元格内直接编辑结构化字段，也支持在详情区统一编辑。
- 支持 PDF、HTML、笔记、图片、链接等附件徽标展示。
- 支持附件编辑 v1：单条目上传本地文件、添加网页链接、重命名附件、删除附件。
- 支持文献研读 v1：打开单篇文献 PDF，显示 PDF 内置目录、连续滚动页面、左右可调三栏布局。
- 支持 Zotero 原生 PDF 标注 v1：文本选择后保存高亮和下划线到 `itemAnnotations`，不修改 PDF 文件本体。
- 详情区笔记支持摘要折叠与展开。
- 支持添加条目 v1：
  - 按 DOI、PMID、arXiv ID、ADS Bibcode、ISBN 等标识符导入。
  - 粘贴 RIS、BibTeX、CSL JSON、PubMed XML 引用文本导入。
  - 导入前自动按强标识符去重，命中已有条目时不重复创建。
- 支持引用导出 v1：
  - 导出已勾选条目的 BibTeX、BibLaTeX、RIS、CSL JSON、CSV。
  - 导出是只读能力，不写 Zotero SQLite，也不影响同步状态。
- 支持左侧文件夹树内管理：根目录新建文件夹、真实文件夹重命名、移动、新建子文件夹、删除文件夹。
- 支持只读连接真实 Zotero 数据目录。
- 支持建立可编辑的本地副本，所有写操作只落到副本。
- 首页源管理支持服务路径选择器：默认进入 demo 文库，可沿虚拟服务器根目录浏览后端/容器可访问的目录。
- 支持浏览器上传本机文库文件夹创建可编辑副本，适合 Docker、局域网或云端预览场景。

## 最近界面能力

- 前端已按 Zotero 官方类型 key 做归一化，并提供中文类型徽标和独立类型筛选。
- 快捷标签改为文库级共享清单；删除快捷标签只影响快捷表，不影响已有条目标签。
- `remark`、`title_zh`、`abstract_zh` 已接入结构化解析与结构化写回。
- 已加入多选复选框和批量操作工具栏占位，便于后续扩展批量功能。
- “删除条目 / 移动条目”已接入批量管理；永久删除会清理本地副本中的相关附件 storage 文件夹。
- 文件夹管理入口已整合到左侧树；根目录只提供新建文件夹，真实文件夹提供重命名、移动、删除和新建子文件夹。
- “添加条目”按钮已接入标识符导入和引用文本导入弹窗，Import translator 路线说明见 `docs/zotero-translators.md`。
- “引用导出”按钮已接入格式文件下载，参考 Zotero Export translators 的常用字段映射。
- “附件编辑”按钮已接入单条目附件管理；网页链接附件 v1 只保存链接，不抓取网页快照。
- “文献研读”按钮已接入单条目 PDF 阅读；右侧智能体对话面板是下一版占位。
- 弹窗、文件夹行内编辑、附件编辑等表单按钮已统一尺寸和视觉样式。
- 源管理页已改为“网页文库”入口，区分本地只读模式、副本编辑模式和浏览器上传文件夹。
- 服务路径选择器只浏览后端允许的目录，显示当前选择目录、子目录和是否包含 `zotero.sqlite`。

## 数据源模式

### 本地只读模式

直接读取指定的 Zotero 数据目录，例如：

```text
C:\Users\<你自己的用户名>\Zotero
```

这种模式不会写入原始 `zotero.sqlite`、`storage/` 或 Zotero 目录中的任何文件。

路径输入框旁的“选择本地路径”指服务运行环境本地路径。Docker 中就是容器里的路径，本地开发时就是当前电脑上的路径。

### 副本编辑模式

程序会把 `zotero.sqlite` 和 `storage/` 复制到应用自己的数据目录里，后续编辑都只作用在这个副本上。

副本可以通过两种方式创建：

- 从服务路径复制：选择后端/容器可访问的目录，例如 Docker 中的 `/opt/demo-data/libraries/<demo-id>`。
- 上传本地文件夹：在浏览器中选择当前电脑上的文库文件夹，上传到服务端后创建副本。

同一个源路径可以创建多个副本，但副本文库名称不能重复。不填写名称时会自动生成不冲突的名称。

项目明确不支持直接写用户真实 Zotero 源库。Zotero 的本地 SQLite 可以读取，但直接修改原始库风险太高。

## 数据规则

- Zotero 原生 `zotero.sqlite` 是文献信息的唯一真实来源。
- `#标签`、评分、阅读状态、期刊/会议等级都来自 Zotero 原生 `tags.name`。
- PDF 高亮和下划线来自 Zotero 原生 `itemAnnotations`，写回时创建 annotation item，不写入 PDF 文件。
- 不新增 Zotero 原生表或字段，不修改 Zotero 原生 schema。
- 应用自己的元数据，例如快捷标签、列设置、界面偏好等，存放在 `app-data/app.sqlite`。

更详细的字段来源、解析规则和写回约束见：
[docs/data-mapping.md](docs/data-mapping.md)

Zotero translators 的调查、可复用边界和添加条目 v1 路线见：
[docs/zotero-translators.md](docs/zotero-translators.md)

## 环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- PDF 阅读器使用本地 vendored PDF.js `3.11.174`，文件位于 `src/zotero_web_library/static/vendor/pdfjs/`。

仓库中的 `.python-version` 已固定为 `3.12`。

## 启动方式

```powershell
uv sync
uv run python -m zotero_web_library.web
```

启动后访问：

```text
http://127.0.0.1:8686
```

默认情况下，本地开发会使用 `./app-data/` 作为应用数据目录。可以用环境变量覆盖：

```powershell
$env:WEB_LIBRARY_DATA_DIR="C:\path\to\app-data"
$env:WEB_LIBRARY_HOST="127.0.0.1"
$env:WEB_LIBRARY_PORT="8686"
$env:WEB_LIBRARY_DEBUG="1"
$env:WEB_LIBRARY_SERVER_ROOTS="C:\"
uv run python -m zotero_web_library.web
```

`WEB_LIBRARY_SERVER_ROOTS` 可选，用于限制“选择本地路径”弹窗中的虚拟服务器根入口；不设置时会自动使用常见入口，例如 Docker 中的 `/opt`、`/app`，Windows 本地的可用盘符。

## Docker 启动

首次 clone 仓库后，如果需要构建带完整 demo 数据的 Docker 镜像，请先拉取 Git LFS 文件：

```powershell
git lfs pull
```

然后构建并启动：

```powershell
docker compose up --build
```

启动后访问：

```text
http://localhost:8686
```

Docker 镜像内置 `demo-data/` 作为演示数据模板。容器首次启动时，如果 `/app/app-data/app.sqlite` 不存在，会自动把 `/opt/demo-data/` 复制到 Docker volume 中。后续重启不会覆盖已有数据。

Docker 中的服务路径选择器默认会进入 `/opt/demo-data/libraries/<demo-id>`。如果要让容器读取 Windows 上的真实文库目录，建议用目录挂载方式把它挂进容器，再使用“从服务路径复制”：

```powershell
docker run -d --name web-library -p 8686:8686 -e WEB_LIBRARY_HOST=0.0.0.0 -e WEB_LIBRARY_PORT=8686 -v web-library-data:/app/app-data -v C:\Users\<你自己的用户名>\Zotero:/host-zotero:ro web-library:latest
```

然后在页面中选择 `/host-zotero`。

浏览器上传文件夹也可以创建副本，但真实 Zotero 目录通常很大。默认上传上限为 8GB、最多 100000 个文件，可用下面的环境变量调整：

```powershell
$env:WEB_LIBRARY_MAX_UPLOAD_BYTES="8589934592"
$env:WEB_LIBRARY_MAX_FORM_PARTS="100000"
```

如需重置 Docker demo 数据：

```powershell
docker compose down -v
docker compose up --build
```

## 测试

```powershell
uv run pytest
```

## 应用数据目录

默认情况下，应用会把元数据和本地副本保存在：

```text
./app-data/
  app.sqlite
  libraries/
    <library-id>/
      zotero.sqlite
      storage/
      source.json
```

`app-data/` 已加入 Git 忽略，因为其中可能包含私人 Zotero 数据和复制出的附件文件。

`demo-data/` 是可公开的演示数据模板，会进入 Docker 镜像，并通过 Git LFS 跟踪。

## 使用注意

- 不要提交 `app-data/`。
- 只有确认可公开的演示数据才放入 `demo-data/`。
- 浏览真实 Zotero 文库时，优先使用只读连接模式。
- 需要实验性编辑时，使用本地副本模式，不要直接碰源库。
