# FMI Report Guard

`fmi-report-guard` polls the public reports feed on [futuremarketinsights.com/reports](https://www.futuremarketinsights.com/reports), reviews only newly published reports, and opens GitHub issues only when a report appears to contain a glaring public-page error.

It is intentionally narrow:

- It looks for obvious forecast-year inconsistencies.
- It checks for clearly broken market math when the page exposes enough numbers.
- It uses OpenAI to flag only high-confidence topic mismatches, hallucinated segmentation, or obvious merged-company duplication.
- It does nothing when a report looks normal.

## How it works

1. The workflow polls FMI's reports AJAX endpoint every 10 minutes.
2. It compares the newest report URLs against `state/seen_reports.json`.
3. It fetches only unseen report pages and extracts public text such as the page title, H1, summary, FAQ snippets, and competitive-language paragraphs.
4. It runs deterministic checks first, then an OpenAI review pass.
5. If findings exist, it creates a GitHub issue for that report and uploads a run artifact.
6. It commits the updated seen-state back into the repo so the next run only handles fresh reports.

## Bootstrap behavior

The first scheduled run seeds the current newest reports into `state/seen_reports.json` and does not audit them. That prevents a backlog flood.

If you want to audit the currently visible reports once, run the workflow manually with `audit_initial=true`.

## Required GitHub setup

1. Create a new GitHub repository from this folder.
2. Add a repository secret named `OPENAI_API_KEY`.
3. In repository settings, allow GitHub Actions to have `Read and write permissions` so the workflow can update `state/seen_reports.json`.
4. Enable the scheduled workflow.

Optional repository variable:

- `OPENAI_MODEL`: defaults to `gpt-5-mini`

## Local usage

Install:

```bash
pip install -e .[dev]
```

Dry-run the newest unseen reports:

```bash
python -m fmi_report_guard.main --dry-run
```

Audit a specific report URL:

```bash
python -m fmi_report_guard.main --force-url https://www.futuremarketinsights.com/reports/hospital-bedsheet-and-pillow-cover-market --dry-run
```

Run tests:

```bash
pytest
```

## Notes

- GitHub Actions schedules are best-effort. A `*/10` cron does not guarantee an exact 10-minute wall-clock run.
- The monitor is tuned to avoid noise. If the model is not highly confident, it should return no findings.
- Do not paste your API key into code or issues. Use the GitHub secret only.
