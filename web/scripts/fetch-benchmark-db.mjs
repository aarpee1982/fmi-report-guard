import { createWriteStream, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pipeline } from "node:stream/promises";

const sourceUrl =
  process.env.FMI_BENCHMARK_DB_URL ||
  "https://github.com/aarpee1982/fmi-report-guard/releases/download/fmi-benchmark-db-2026-05-26/fmi_global_benchmarks.sqlite.zip";

const outputPath = resolve("public", "fmi_global_benchmarks.sqlite.zip");

async function download(url, redirectCount = 0) {
  if (redirectCount > 5) {
    throw new Error("Too many redirects while downloading benchmark DB.");
  }

  const response = await fetch(url);
  if ([301, 302, 303, 307, 308].includes(response.status)) {
    const location = response.headers.get("location");
    if (!location) throw new Error(`Redirect without location: ${response.status}`);
    return download(new URL(location, url).toString(), redirectCount + 1);
  }
  if (!response.ok || !response.body) {
    throw new Error(`Benchmark DB download failed: ${response.status} ${response.statusText}`);
  }

  mkdirSync(dirname(outputPath), { recursive: true });
  await pipeline(response.body, createWriteStream(outputPath));
}

if (existsSync(outputPath) && process.env.FORCE_DB_DOWNLOAD !== "true") {
  console.log(`Benchmark DB already exists at ${outputPath}`);
} else {
  console.log(`Downloading benchmark DB from ${sourceUrl}`);
  await download(sourceUrl);
  console.log(`Benchmark DB saved to ${outputPath}`);
}
