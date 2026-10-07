import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

const PY = ["python3", "-m", "minireport.webapi_cli"];

interface RunBody {
  action: "generate" | "apply_summary" | "apply_edits";
  scenario?: string;
  ai?: boolean;
  text?: string;
  lower?: number;
  upper?: number;
  sample_id?: string;
  value?: number;
  value_changed?: boolean;
}

async function runPython(body: RunBody) {
  const { spawn } = await import("node:child_process");
  const path = await import("node:path");

  // repo root = web/.. (works in dev and after `next build`)
  const root = path.resolve(process.cwd(), "..");

  return new Promise<{ status: number; data: unknown }>((resolve) => {
    const proc = spawn(PY[0], [...PY.slice(1), JSON.stringify(body)], {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "src"), PYTHONUNBUFFERED: "1" },
      // stdin must be EOF immediately: the bridge reads stdin to EOF, and an
      // inherited never-closing stdin would block it forever
      stdio: ["ignore", "pipe", "pipe"],
    });

    let out = "";
    let err = "";
    proc.stdout.setMaxListeners(0);
    proc.stdout.on("data", (d) => (out += d));
    proc.stderr.on("data", (d) => (err += d));
    proc.on("close", (code) => {
      if (code === 0 && out.trim().length > 0) {
        try {
          resolve({ status: 200, data: JSON.parse(out) });
        } catch (e) {
          resolve({ status: 500, data: { error: "bad JSON from engine: " + String(e).slice(0, 200), stderr: err.slice(-800) } });
        }
      } else {
        resolve({ status: 500, data: { error: err.trim().split("\n").slice(-3).join(" | ") || `engine exited ${code}` } });
      }
    });
    proc.on("error", (e) => resolve({ status: 500, data: { error: "engine spawn failed: " + e.message } }));
  });
}

export async function POST(req: Request) {
  let body: RunBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  switch (body.action) {
    case "generate":
    case "apply_summary":
    case "apply_edits":
      break;
    default:
      return NextResponse.json({ error: "unknown action" }, { status: 400 });
  }

  const { status, data } = await runPython(body);
  return NextResponse.json(data, { status });
}
