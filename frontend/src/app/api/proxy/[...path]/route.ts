import { NextRequest, NextResponse } from "next/server";
import { isAllowedOrigin } from "@/lib/originGuard";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Server-only proxy: browser talks to /api/proxy/*, this forwards to FastAPI
 * and injects X-Admin-Token. Secrets never ship to the client bundle.
 */

type Rule = {
  methods: ReadonlySet<string>;
  pattern: RegExp;
};

const ALLOWLIST: Rule[] = [
  { methods: new Set(["GET"]), pattern: /^health$/ },
  { methods: new Set(["GET"]), pattern: /^organization$/ },
  { methods: new Set(["GET"]), pattern: /^customers$/ },
  { methods: new Set(["GET", "PATCH"]), pattern: /^customers\/[^/]+$/ },
  { methods: new Set(["GET"]), pattern: /^invoices$/ },
  { methods: new Set(["GET"]), pattern: /^invoices\/open$/ },
  { methods: new Set(["GET"]), pattern: /^invoices\/[^/]+$/ },
  { methods: new Set(["POST"]), pattern: /^admin\/reset$/ },
  { methods: new Set(["POST"]), pattern: /^reconciliation\/upload$/ },
  { methods: new Set(["GET"]), pattern: /^reconciliation\/statements$/ },
  {
    methods: new Set(["GET"]),
    pattern: /^reconciliation\/statements\/[^/]+$/,
  },
  {
    methods: new Set(["POST"]),
    pattern: /^reconciliation\/suggestions\/[^/]+\/(approve|reject|choose)$/,
  },
  { methods: new Set(["POST"]), pattern: /^collections\/reminders\/send$/ },
  { methods: new Set(["POST"]), pattern: /^collections\/inbox\/check$/ },
  { methods: new Set(["GET"]), pattern: /^collections\/conversations$/ },
  {
    methods: new Set(["GET"]),
    pattern: /^collections\/conversations\/[^/]+$/,
  },
  { methods: new Set(["GET"]), pattern: /^collections\/needs-attention$/ },
  {
    methods: new Set(["PATCH"]),
    pattern: /^collections\/needs-attention\/[^/]+$/,
  },
  {
    methods: new Set(["POST"]),
    pattern: /^collections\/needs-attention\/[^/]+\/(send|dismiss)$/,
  },
];

function isAllowed(method: string, apiPath: string): boolean {
  return ALLOWLIST.some(
    (rule) => rule.methods.has(method) && rule.pattern.test(apiPath),
  );
}

function backendBase(): string {
  const base = process.env.BACKEND_URL?.replace(/\/$/, "");
  if (!base) {
    throw new Error("BACKEND_URL is not configured");
  }
  return base;
}

function adminToken(): string {
  const token = process.env.ADMIN_TOKEN;
  if (!token) {
    throw new Error("ADMIN_TOKEN is not configured");
  }
  return token;
}

let warnedTokenMismatch = false;
function warnTokenMismatchOnce(): void {
  if (warnedTokenMismatch) return;
  warnedTokenMismatch = true;
  console.warn(
    "[proxy] Backend rejected ADMIN_TOKEN (401). Frontend ADMIN_TOKEN must equal backend ADMIN_API_TOKEN.",
  );
}

async function forward(
  request: NextRequest,
  pathParts: string[],
): Promise<NextResponse> {
  const method = request.method.toUpperCase();
  const apiPath = pathParts.map(decodeURIComponent).join("/");

  if (
    !isAllowedOrigin(method, {
      origin: request.headers.get("origin"),
      host: request.headers.get("host"),
      secFetchSite: request.headers.get("sec-fetch-site"),
    })
  ) {
    return NextResponse.json(
      { detail: "Cross-origin request blocked" },
      { status: 403 },
    );
  }

  if (!isAllowed(method, apiPath)) {
    return NextResponse.json(
      { detail: `Proxy path/method not allowlisted: ${method} ${apiPath}` },
      { status: 403 },
    );
  }

  let base: string;
  let token: string;
  try {
    base = backendBase();
    token = adminToken();
  } catch (err) {
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Proxy misconfigured" },
      { status: 500 },
    );
  }

  const target = new URL(`${base}/api/v1/${apiPath}`);
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.append(key, value);
  });

  const headers = new Headers();
  headers.set("Accept", "application/json");
  headers.set("X-Admin-Token", token);

  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  const init: RequestInit = {
    method,
    headers,
    cache: "no-store",
  };

  if (method !== "GET" && method !== "HEAD") {
    // Preserve multipart boundaries for CSV upload
    if (contentType?.includes("multipart/form-data")) {
      init.body = await request.arrayBuffer();
    } else {
      const body = await request.text();
      if (body) {
        init.body = body;
      }
    }
  }

  try {
    const upstream = await fetch(target, init);
    const text = await upstream.text();
    if (upstream.status === 401) {
      warnTokenMismatchOnce();
    }
    const responseHeaders = new Headers();
    const upstreamCt = upstream.headers.get("content-type");
    if (upstreamCt) {
      responseHeaders.set("Content-Type", upstreamCt);
    }
    responseHeaders.set("Cache-Control", "no-store");
    return new NextResponse(text, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (err) {
    return NextResponse.json(
      {
        detail:
          err instanceof Error
            ? `Backend unreachable: ${err.message}`
            : "Backend unreachable",
      },
      { status: 502 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function POST(request: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function PATCH(request: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(request, path);
}
