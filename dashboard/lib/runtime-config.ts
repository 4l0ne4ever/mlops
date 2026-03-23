import "server-only";

import fs from "node:fs/promises";
import path from "node:path";

import type { RuntimeAppConfig } from "@/lib/types";

export async function getRuntimeAppConfig(): Promise<RuntimeAppConfig> {
  const configPath = process.env.APP_CONFIG
    ? path.resolve(process.cwd(), "..", process.env.APP_CONFIG)
    : path.resolve(process.cwd(), "..", "configs", "local.json");

  try {
    const content = await fs.readFile(configPath, "utf-8");
    const parsed = JSON.parse(content) as {
      environment?: string;
      target_app?: { production_url?: string; staging_url?: string };
    };

    return {
      environment: parsed.environment ?? "local",
      productionUrl: parsed.target_app?.production_url ?? "http://localhost:9000",
      stagingUrl: parsed.target_app?.staging_url ?? "http://localhost:9001",
    };
  } catch {
    return {
      environment: "local",
      productionUrl: "http://localhost:9000",
      stagingUrl: "http://localhost:9001",
    };
  }
}