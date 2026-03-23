import "server-only";

type MCPServerName = "storage" | "monitor" | "deploy";

const SERVER_URLS: Record<MCPServerName, string> = {
  storage: process.env.MCP_STORAGE_URL ?? "http://localhost:8000",
  monitor: process.env.MCP_MONITOR_URL ?? "http://localhost:8001",
  deploy: process.env.MCP_DEPLOY_URL ?? "http://localhost:8002",
};

const MCP_HEADERS = {
  "Content-Type": "application/json",
  Accept: "application/json, text/event-stream",
};

const MCP_TIMEOUT_MS = 15000;

function parseSsePayload(body: string): unknown {
  const dataLines = body
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());

  if (!dataLines.length) {
    return null;
  }

  return JSON.parse(dataLines[dataLines.length - 1]);
}

async function parseMcpHttpBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  const body = await response.text();
  if (contentType.includes("text/event-stream")) {
    return parseSsePayload(body);
  }

  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

async function initializeSession(server: MCPServerName): Promise<string> {
  const url = `${SERVER_URLS[server]}/mcp`;
  const initializeResponse = await fetch(url, {
    method: "POST",
    headers: MCP_HEADERS,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: {
          name: "agentops-dashboard",
          version: "0.1.0",
        },
      },
    }),
    cache: "no-store",
    signal: AbortSignal.timeout(MCP_TIMEOUT_MS),
  });

  if (!initializeResponse.ok) {
    throw new Error(`MCP ${server} initialize failed: HTTP ${initializeResponse.status}`);
  }

  const sessionId = initializeResponse.headers.get("mcp-session-id");
  if (!sessionId) {
    throw new Error(`MCP ${server} initialize failed: missing session ID`);
  }

  const initializePayload = await parseMcpHttpBody(initializeResponse);
  parseMcpResponse(initializePayload);

  const initializedResponse = await fetch(url, {
    method: "POST",
    headers: {
      ...MCP_HEADERS,
      "mcp-session-id": sessionId,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "notifications/initialized",
      params: {},
    }),
    cache: "no-store",
    signal: AbortSignal.timeout(MCP_TIMEOUT_MS),
  });

  if (!initializedResponse.ok) {
    throw new Error(
      `MCP ${server} initialized notification failed: HTTP ${initializedResponse.status}`,
    );
  }
  return sessionId;
}

function parseMcpResponse(data: unknown): unknown {
  if (!data || typeof data !== "object") {
    return data;
  }

  const record = data as Record<string, unknown>;
  if (record.error) {
    throw new Error(`MCP error: ${JSON.stringify(record.error)}`);
  }

  const result = (record.result as Record<string, unknown> | undefined) ?? record;
  const content = result.content;

  if (Array.isArray(content)) {
    for (const block of content) {
      if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
        const text = (block as { text?: string }).text ?? "";
        try {
          return JSON.parse(text);
        } catch {
          return text;
        }
      }
    }
  }

  return result;
}

export async function callMcpTool<T>(
  server: MCPServerName,
  toolName: string,
  argumentsPayload: Record<string, unknown>,
): Promise<T> {
  const url = `${SERVER_URLS[server]}/mcp`;
  const execute = async (sessionId: string): Promise<Response> =>
    fetch(url, {
      method: "POST",
      headers: {
        ...MCP_HEADERS,
        "mcp-session-id": sessionId,
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: {
          name: toolName,
          arguments: argumentsPayload,
        },
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(MCP_TIMEOUT_MS),
    });

  let sessionId = await initializeSession(server);
  let response = await execute(sessionId);

  if (response.status === 400) {
    sessionId = await initializeSession(server);
    response = await execute(sessionId);
  }

  if (!response.ok) {
    throw new Error(`MCP ${server}.${toolName} failed: HTTP ${response.status}`);
  }

  const data = await parseMcpHttpBody(response);
  return parseMcpResponse(data) as T;
}