---
name: multi-source-retrieval
description: Use this skill for multi-source heterogeneous retrieval in this Zotero web library project: list configured sources, plan V4 keyword/natural-language searches, run provider-backed searches, inspect candidates, score candidates with AI, and summarize coverage.
---

# Multi-Source Retrieval

Use the project CLI only. Do not bypass project providers, scrape independently, or import items into Zotero automatically.

## Commands

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli <command> --library-id <library_id>
```

Every command prints JSON.

## Workflow

1. List sources:

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli sources --library-id <library_id>
```

2. Plan the search.

Use `--route keyword` for exact topic terms. Use `--route natural_language` for user descriptions that need translation, synonyms, narrower/broader terms, or per-source query adaptation.

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli plan --library-id <library_id> --route natural_language --input "中文或英文检索需求" --mode quality --material-types paper,code,model,dataset,benchmark,website
```

3. Execute searches using the planned query strings and source list:

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli search --library-id <library_id> --query "bimanual manipulation robot" --sources crossref,arxiv,semanticscholar,github --limit 10
```

4. Read candidates from a saved run:

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli candidates --library-id <library_id> --run-id <run_id>
```

5. Optionally AI-score candidates:

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli ai-score --library-id <library_id> --query "user retrieval need" --run-id <run_id>
```

6. Summarize coverage:

```powershell
.venv\Scripts\python.exe -m zotero_web_library.retrieval_cli coverage --library-id <library_id> --guided-job-id <job_id>
```

## Boundaries

- Never submit API keys, tokens, local private paths, or screenshots.
- Do not auto-import candidates. Return a candidate table and let the user choose.
- Do not call external search tools outside this project unless the user explicitly asks.
- If the model is not configured, natural-language planning should fail clearly; switch to keyword search only with user approval.
