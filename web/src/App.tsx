import { ChangeEvent, useMemo, useState } from "react";
import initSqlJs, { Database } from "sql.js";
import wasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import { unzipSync } from "fflate";
import {
  AlertTriangle,
  ClipboardCopy,
  CheckCircle2,
  DatabaseZap,
  Download,
  FileUp,
  Link as LinkIcon,
  Loader2,
  Search,
  ShieldAlert,
  ShieldCheck
} from "lucide-react";

type Unit = "USD million" | "USD billion";

type BenchmarkMarket = {
  marketName: string;
  url: string;
  category: string;
  estimatedYear: number;
  estimatedValueUsdMn: number;
  forecastYear: number;
  forecastValueUsdMn: number;
  cagrPercent: number;
};

type DbState =
  | { status: "idle"; message: string }
  | { status: "loading"; message: string }
  | { status: "ready"; message: string; source: string; rows: number }
  | { status: "error"; message: string };

type Relation = "candidate_subset" | "candidate_parent" | "self_check";

type Match = {
  relation: Relation;
  benchmark: BenchmarkMarket;
  issue?: string;
  recommendation?: string;
};

const DEFAULT_DB_URL =
  import.meta.env.VITE_BENCHMARK_DB_URL || "/fmi_global_benchmarks.sqlite.zip";

const STOPWORDS = new Set([
  "market",
  "global",
  "industry",
  "report",
  "analysis",
  "forecast",
  "outlook",
  "size",
  "share",
  "and",
  "or",
  "of",
  "the",
  "in",
  "for",
  "by",
  "to"
]);

const REGION_WORDS = new Set([
  "africa",
  "asia",
  "australia",
  "brazil",
  "canada",
  "china",
  "europe",
  "france",
  "gcc",
  "germany",
  "india",
  "indonesia",
  "italy",
  "japan",
  "korea",
  "latin",
  "mexico",
  "middle",
  "north",
  "russia",
  "saudi",
  "south",
  "spain",
  "turkey",
  "uae",
  "uk",
  "united",
  "usa",
  "western"
]);

function titleTokens(title: string): Set<string> {
  const tokens = title.toLowerCase().match(/[a-z0-9]+/g) ?? [];
  return new Set(
    tokens.filter(
      (token) => token.length > 1 && !STOPWORDS.has(token) && !REGION_WORDS.has(token)
    )
  );
}

function isStrictSubset(left: Set<string>, right: Set<string>): boolean {
  if (left.size >= right.size) return false;
  for (const token of left) {
    if (!right.has(token)) return false;
  }
  return true;
}

function relationTo(candidateTitle: string, benchmarkTitle: string): Relation | null {
  const candidate = titleTokens(candidateTitle);
  const benchmark = titleTokens(benchmarkTitle);
  if (!candidate.size || !benchmark.size) return null;
  if (isStrictSubset(benchmark, candidate)) return "candidate_subset";
  if (isStrictSubset(candidate, benchmark)) return "candidate_parent";
  return null;
}

function toUsdMn(value: string, unit: Unit): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return unit === "USD billion" ? parsed * 1000 : parsed;
}

function formatUsdMn(value: number): string {
  if (value >= 1000) return `USD ${(value / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} billion`;
  return `USD ${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} million`;
}

function decodeDbBytes(bytes: Uint8Array, fileName: string): Uint8Array {
  if (!fileName.toLowerCase().endsWith(".zip")) return bytes;
  const files = unzipSync(bytes);
  const dbEntry = Object.entries(files).find(([name]) =>
    /\.(sqlite|sqlite3|db)$/i.test(name)
  );
  if (!dbEntry) {
    throw new Error("Zip loaded, but no .sqlite/.db file found inside.");
  }
  return dbEntry[1];
}

function readRows(db: Database): BenchmarkMarket[] {
  const result = db.exec(`
    SELECT market_name, url, category, estimated_year, estimated_value_usd_mn,
           forecast_year, forecast_value_usd_mn, cagr_percent
    FROM valid_global_benchmarks
  `);
  const table = result[0];
  if (!table) return [];
  return table.values.map((row) => ({
    marketName: String(row[0]),
    url: String(row[1]),
    category: String(row[2] ?? ""),
    estimatedYear: Number(row[3]),
    estimatedValueUsdMn: Number(row[4]),
    forecastYear: Number(row[5]),
    forecastValueUsdMn: Number(row[6]),
    cagrPercent: Number(row[7])
  }));
}

function cagrForecast(estimatedUsdMn: number, cagrPercent: number, years = 10): number {
  return estimatedUsdMn * (1 + cagrPercent / 100) ** years;
}

function pctGap(a: number, b: number): number {
  return Math.abs(a - b) / Math.max(Math.abs(b), 1);
}

function compareCandidate(
  title: string,
  candidate2026UsdMn: number,
  candidate2036UsdMn: number,
  cagrPercent: number,
  benchmarks: BenchmarkMarket[]
): Match[] {
  const matches: Match[] = [];
  const calculated2036 = cagrForecast(candidate2026UsdMn, cagrPercent);

  for (const benchmark of benchmarks) {
    const relation = relationTo(title, benchmark.marketName);
    if (!relation) continue;

    const issueParts: string[] = [];
    const recommendationParts: string[] = [];

    if (relation === "candidate_subset") {
      if (candidate2026UsdMn > benchmark.estimatedValueUsdMn) {
        issueParts.push(
          `Entered 2026 value is bigger than parent benchmark ${benchmark.estimatedYear} value (${formatUsdMn(candidate2026UsdMn)} > ${formatUsdMn(benchmark.estimatedValueUsdMn)}).`
        );
        recommendationParts.push(
          `Set 2026 below ${formatUsdMn(benchmark.estimatedValueUsdMn)} or confirm the title is not a child of "${benchmark.marketName}".`
        );
      }
      if (candidate2036UsdMn > benchmark.forecastValueUsdMn) {
        issueParts.push(
          `Entered 2036 value is bigger than parent benchmark ${benchmark.forecastYear} value (${formatUsdMn(candidate2036UsdMn)} > ${formatUsdMn(benchmark.forecastValueUsdMn)}).`
        );
        recommendationParts.push(
          `Set 2036 below ${formatUsdMn(benchmark.forecastValueUsdMn)} or use a narrower/lower forecast.`
        );
      }
    }

    if (relation === "candidate_parent") {
      if (candidate2026UsdMn < benchmark.estimatedValueUsdMn) {
        issueParts.push(
          `Entered 2026 value is smaller than child benchmark ${benchmark.estimatedYear} value (${formatUsdMn(candidate2026UsdMn)} < ${formatUsdMn(benchmark.estimatedValueUsdMn)}).`
        );
        recommendationParts.push(
          `Raise 2026 above ${formatUsdMn(benchmark.estimatedValueUsdMn)} or confirm "${benchmark.marketName}" is not a child market.`
        );
      }
      if (candidate2036UsdMn < benchmark.forecastValueUsdMn) {
        issueParts.push(
          `Entered 2036 value is smaller than child benchmark ${benchmark.forecastYear} value (${formatUsdMn(candidate2036UsdMn)} < ${formatUsdMn(benchmark.forecastValueUsdMn)}).`
        );
        recommendationParts.push(
          `Raise 2036 above ${formatUsdMn(benchmark.forecastValueUsdMn)} or adjust the parent-child relationship.`
        );
      }
    }

    if (issueParts.length) {
      matches.push({
        relation,
        benchmark,
        issue: issueParts.join(" "),
        recommendation: recommendationParts.join(" ")
      });
    } else {
      matches.push({ relation, benchmark });
    }
  }

  const sorted = matches.sort((a, b) => {
    if (a.issue && !b.issue) return -1;
    if (!a.issue && b.issue) return 1;
    const aSize = a.benchmark.estimatedValueUsdMn + a.benchmark.forecastValueUsdMn;
    const bSize = b.benchmark.estimatedValueUsdMn + b.benchmark.forecastValueUsdMn;
    return bSize - aSize;
  });

  const internalMismatch =
    pctGap(candidate2036UsdMn, calculated2036) > 0.025
      ? [
          {
            relation: "self_check" as Relation,
            benchmark: {
              marketName: "Candidate CAGR self-check",
              url: "",
              category: "Entered values",
              estimatedYear: 2026,
              estimatedValueUsdMn: candidate2026UsdMn,
              forecastYear: 2036,
              forecastValueUsdMn: calculated2036,
              cagrPercent
            },
            issue: `Entered 2036 value does not align with 2026 value and CAGR. ${formatUsdMn(candidate2026UsdMn)} at ${cagrPercent}% CAGR implies about ${formatUsdMn(calculated2036)} in 2036.`,
            recommendation: `Change 2036 to about ${formatUsdMn(calculated2036)}, or revise the CAGR.`
          }
        ]
      : [];

  return [...internalMismatch, ...sorted].slice(0, 40);
}

function App() {
  const [dbState, setDbState] = useState<DbState>({
    status: "idle",
    message: "Load FMI benchmark DB to begin."
  });
  const [benchmarks, setBenchmarks] = useState<BenchmarkMarket[]>([]);
  const [title, setTitle] = useState("Android Based Smartphone Market");
  const [value2026, setValue2026] = useState("900");
  const [unit2026, setUnit2026] = useState<Unit>("USD million");
  const [cagr, setCagr] = useState("6.5");
  const [value2036, setValue2036] = useState("1690");
  const [unit2036, setUnit2036] = useState<Unit>("USD million");
  const [searchText, setSearchText] = useState("");
  const [copyState, setCopyState] = useState("Copy issues");

  async function loadBytes(bytes: Uint8Array, source: string) {
    setDbState({ status: "loading", message: "Opening SQLite in browser..." });
    const dbBytes = decodeDbBytes(bytes, source);
    const SQL = await initSqlJs({ locateFile: () => wasmUrl });
    const db = new SQL.Database(dbBytes);
    const rows = readRows(db);
    db.close();
    setBenchmarks(rows);
    setDbState({
      status: "ready",
      source,
      rows: rows.length,
      message: `${rows.length.toLocaleString()} benchmark rows ready.`
    });
  }

  async function fetchDefaultDb() {
    try {
      setDbState({ status: "loading", message: "Loading bundled benchmark ZIP..." });
      const response = await fetch(DEFAULT_DB_URL);
      if (!response.ok) throw new Error(`Download failed: ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      await loadBytes(bytes, DEFAULT_DB_URL);
    } catch (error) {
      setDbState({
        status: "error",
        message:
          error instanceof Error
            ? `${error.message}. Upload the local DB ZIP if the bundled file is not present.`
            : "Unable to load DB."
      });
    }
  }

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setDbState({ status: "loading", message: `Reading ${file.name}...` });
      const bytes = new Uint8Array(await file.arrayBuffer());
      await loadBytes(bytes, file.name);
    } catch (error) {
      setDbState({
        status: "error",
        message: error instanceof Error ? error.message : "Unable to load DB file."
      });
    }
  }

  const candidate2026 = toUsdMn(value2026, unit2026);
  const candidate2036 = toUsdMn(value2036, unit2036);
  const cagrValue = Number(cagr);
  const canCheck =
    dbState.status === "ready" &&
    title.trim().length > 2 &&
    candidate2026 !== null &&
    candidate2036 !== null &&
    Number.isFinite(cagrValue);

  const matches = useMemo(() => {
    if (!canCheck || candidate2026 === null || candidate2036 === null) return [];
    return compareCandidate(title, candidate2026, candidate2036, cagrValue, benchmarks);
  }, [benchmarks, canCheck, candidate2026, candidate2036, cagrValue, title]);

  const issues = matches.filter((match) => match.issue);
  const filteredMatches = matches.filter((match) => {
    if (!searchText.trim()) return true;
    const haystack = `${match.benchmark.marketName} ${match.benchmark.url} ${match.issue ?? ""}`.toLowerCase();
    return haystack.includes(searchText.toLowerCase());
  });
  const controlFText = `${title.trim()} | 2026 ${formatUsdMn(candidate2026 ?? 0)} | 2036 ${formatUsdMn(candidate2036 ?? 0)}`;
  const copyableIssues = issues.length
    ? issues
        .map(
          (match, index) =>
            [
              `${index + 1}. Market name: ${match.benchmark.marketName}`,
              `URL: ${match.benchmark.url || "Candidate entered values"}`,
              `Issue: ${match.issue}`,
              `Control+F: ${controlFText}`,
              `Change with: ${match.recommendation}`
            ].join("\n")
        )
        .join("\n\n")
    : `No parent-child size violation found for ${title.trim() || "entered market"}.`;

  async function copyIssues() {
    await navigator.clipboard.writeText(copyableIssues);
    setCopyState("Copied");
    window.setTimeout(() => setCopyState("Copy issues"), 1400);
  }

  return (
    <main className="app">
      <aside className="sidebar">
        <div className="brand">
          <DatabaseZap aria-hidden="true" />
          <div>
            <strong>FMI Benchmark Checker</strong>
            <span>Parent-child market guard</span>
          </div>
        </div>

        <section className="panel">
          <h2>Source of truth</h2>
          <p className="muted">
            Load the 500MB SQLite DB or the zipped release file. Processing stays inside this browser.
          </p>
          <div className={`db-status ${dbState.status}`}>
            {dbState.status === "ready" ? <CheckCircle2 /> : dbState.status === "loading" ? <Loader2 className="spin" /> : <AlertTriangle />}
            <span>{dbState.message}</span>
          </div>
          {dbState.status === "ready" && (
            <dl className="stats">
              <div>
                <dt>Rows</dt>
                <dd>{dbState.rows.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{dbState.source}</dd>
              </div>
            </dl>
          )}
          <button className="primary" type="button" onClick={fetchDefaultDb} disabled={dbState.status === "loading"}>
            <Download aria-hidden="true" />
            Load bundled DB
          </button>
          <label className="file-button">
            <FileUp aria-hidden="true" />
            Upload SQLite or ZIP
            <input accept=".sqlite,.sqlite3,.db,.zip" type="file" onChange={onFileChange} />
          </label>
        </section>

        <section className="panel compact">
          <h2>Rule</h2>
          <p>
            If new title is a child of an old market, its 2026 and 2036 values cannot exceed the parent.
            If new title is a parent, it cannot be smaller than an existing child.
          </p>
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Check a new market number before publishing</h1>
            <p>Enter title, 2026 value, CAGR, and 2036 value. The app compares against FMI global benchmarks.</p>
          </div>
        </header>

        <section className="entry-grid">
          <label className="field wide">
            <span>Market title</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Example: Android Based Smartphone Market" />
          </label>
          <label className="field">
            <span>2026 market size</span>
            <input inputMode="decimal" value={value2026} onChange={(event) => setValue2026(event.target.value)} />
          </label>
          <label className="field">
            <span>2026 unit</span>
            <select value={unit2026} onChange={(event) => setUnit2026(event.target.value as Unit)}>
              <option>USD million</option>
              <option>USD billion</option>
            </select>
          </label>
          <label className="field">
            <span>CAGR %</span>
            <input inputMode="decimal" value={cagr} onChange={(event) => setCagr(event.target.value)} />
          </label>
          <label className="field">
            <span>2036 market size</span>
            <input inputMode="decimal" value={value2036} onChange={(event) => setValue2036(event.target.value)} />
          </label>
          <label className="field">
            <span>2036 unit</span>
            <select value={unit2036} onChange={(event) => setUnit2036(event.target.value as Unit)}>
              <option>USD million</option>
              <option>USD billion</option>
            </select>
          </label>
        </section>

        <section className={`verdict ${!canCheck ? "neutral" : issues.length ? "bad" : "good"}`}>
          <div className="verdict-icon">
            {!canCheck ? <Search /> : issues.length ? <ShieldAlert /> : <ShieldCheck />}
          </div>
          <div>
            <h2>
              {!canCheck
                ? "Load DB and enter all numbers"
                : issues.length
                  ? `${issues.length} parent-child issue${issues.length === 1 ? "" : "s"} found`
                  : "No parent-child size violation found"}
            </h2>
            <p>
              {!canCheck
                ? "The checker needs a loaded benchmark table and valid numeric inputs."
                : issues.length
                  ? "Review the exact benchmark rows and correction text below."
                  : `${matches.length} possible parent/child benchmark match${matches.length === 1 ? "" : "es"} reviewed.`}
            </p>
          </div>
        </section>

        <section className="results">
          <div className="results-head">
            <div>
              <h2>Editor output</h2>
              <p>Use the issue and replacement text directly while reviewing the new report draft.</p>
            </div>
            <label className="search-box">
              <Search aria-hidden="true" />
              <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Filter matches" />
            </label>
            <button className="copy-button" type="button" onClick={copyIssues} disabled={!canCheck}>
              <ClipboardCopy aria-hidden="true" />
              {copyState}
            </button>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Market name</th>
                  <th>URL</th>
                  <th>Relationship</th>
                  <th>Benchmark values</th>
                  <th>Issues</th>
                  <th>Control+F</th>
                  <th>Change with</th>
                </tr>
              </thead>
              <tbody>
                {filteredMatches.length ? (
                  filteredMatches.map((match, index) => (
                    <tr key={`${match.benchmark.url || match.benchmark.marketName}-${index}`} className={match.issue ? "issue-row" : ""}>
                      <td>
                        <strong>{match.benchmark.marketName}</strong>
                        <span className="subline">{match.benchmark.category || "Benchmark"}</span>
                      </td>
                      <td>
                        {match.benchmark.url ? (
                          <a href={match.benchmark.url} target="_blank" rel="noreferrer" title={match.benchmark.url}>
                            <LinkIcon aria-hidden="true" />
                            Open
                          </a>
                        ) : (
                          <span className="subline">Candidate row</span>
                        )}
                      </td>
                      <td>
                        {match.relation === "self_check"
                          ? "Entered values"
                          : match.relation === "candidate_subset"
                            ? "New title is child"
                            : "New title is parent"}
                      </td>
                      <td>
                        <span>{match.benchmark.estimatedYear}: {formatUsdMn(match.benchmark.estimatedValueUsdMn)}</span>
                        <span>{match.benchmark.forecastYear}: {formatUsdMn(match.benchmark.forecastValueUsdMn)}</span>
                        <span>CAGR: {match.benchmark.cagrPercent.toFixed(2)}%</span>
                      </td>
                      <td>{match.issue ?? "No size conflict. Manual topic check still needed."}</td>
                      <td className="controlf">{match.issue ? controlFText : title.trim()}</td>
                      <td>{match.recommendation ?? "No value change required from this benchmark."}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="empty">
                      No matches yet. Load DB, then enter a title and numbers.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  );
}

export default App;
