import { NextResponse } from "next/server";
import path from "node:path";

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
  input_dir?: string;
  run_key?: string;
  run?: string;
}

async function runPython(body: RunBody) {
  const { spawn } = await import("node:child_process");

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
      // the bridge prints a JSON object on stdout even on failure
      if (out.trim().length > 0) {
        try {
          const parsed = JSON.parse(out);
          resolve({ status: parsed.error ? 500 : 200, data: parsed });
          return;
        } catch {
          /* fall through to stderr */
        }
      }
      resolve({
        status: 500,
        data: { error: err.trim().split("\n").slice(-3).join(" | ") || `engine exited ${code}` },
      });
    });
    proc.on("error", (e) => resolve({ status: 500, data: { error: "engine spawn failed: " + e.message } }));
  });
}

export async function POST(req: Request) {
  let body: RunBody;

  if ((req.headers.get("content-type") || "").includes("multipart/form-data")) {
    // ---- user-uploaded input set ------------------------------------------
    const form = await req.formData();
    const ai = form.get("ai") === "true";
    const { randomUUID } = await import("node:crypto");
    const { mkdir, writeFile } = await import("node:fs/promises");
    const os = await import("node:os");

    const runKey = "custom_" + randomUUID().slice(0, 8);
    const inputDir = path.join(os.tmpdir(), "minireport", "uploads", runKey);
    await mkdir(inputDir, { recursive: true });

    // canonical names the engine expects; other fields keep their names
    const canon: Record<string, string> = {
      protocol: "protocol.md",
      results: "results.csv",
      template: "report_template.docx",
    };
    for (const [field, stored] of Object.entries(canon)) {
      const f = form.get(field);
      if (f instanceof File && f.size > 0) {
        await writeFile(path.join(inputDir, stored), Buffer.from(await f.arrayBuffer()));
      }
    }
    let refs = 0, atts = 0;
    for (const f of form.getAll("references")) {
      if (f instanceof File && f.size > 0) {
        await writeFile(path.join(inputDir, f.name), Buffer.from(await f.arrayBuffer()));
        refs++;
      }
    }
    for (const f of form.getAll("attachments")) {
      if (f instanceof File && f.size > 0) {
        await writeFile(path.join(inputDir, f.name), Buffer.from(await f.arrayBuffer()));
        atts++;
      }
    }

    const missing: string[] = [];
    for (const f of ["protocol.md", "results.csv", "report_template.docx"]) {
      if (!(await import("node:fs/promises")).stat(path.join(inputDir, f)).catch(() => null)) missing.push(f);
    }
    if (missing.length) {
      return NextResponse.json(
        { error: `upload incomplete — missing ${missing.join(", ")}. ` +
                 "the protocol must be named protocol.md (or .txt), the results file results.csv, " +
                 "the template report_template.docx." },
        { status: 400 }
      );
    }

    body = { action: "generate", input_dir: inputDir, run_key: runKey, ai };
  } else {
    try {
      body = await req.json();
    } catch {
      return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
    }
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
