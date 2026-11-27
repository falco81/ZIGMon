import { spawn as nodeSpawn, type SpawnOptions } from "node:child_process";
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

/**
 * Keeps the deck key (zsd_...) encrypted at rest. On Windows: DPAPI for the current user
 * (System.Security.Cryptography.ProtectedData through PowerShell), so only this Windows
 * account on this computer can read it back. The secret goes in on stdin and comes out on
 * stdout - never on a command line, never in an environment variable, never logged.
 */
export interface Protector {
  protect(plain: string): Promise<string>;
  unprotect(blob: string): Promise<string>;
}

export class ProtectorError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProtectorError";
  }
}

/** Extra entropy so another program running as the same user cannot simply call Unprotect on our blob by accident. */
const ENTROPY_B64 = Buffer.from("ZIGMon for Stream Deck/token/v1", "utf8").toString("base64");

/**
 * The fixed PowerShell program: reads one line "P <base64>" or "U <base64>" from stdin and
 * writes base64 to stdout. It is constant text - nothing of the secret is ever put into it.
 */
export const DPAPI_SCRIPT = [
  "$ErrorActionPreference = 'Stop'",
  "Add-Type -AssemblyName System.Security",
  "$line = [Console]::In.ReadLine()",
  "if ($null -eq $line -or $line.Length -lt 3) { exit 2 }",
  "$mode = $line.Substring(0, 1)",
  "$data = [Convert]::FromBase64String($line.Substring(2))",
  `$entropy = [Convert]::FromBase64String('${ENTROPY_B64}')`,
  "$scope = [System.Security.Cryptography.DataProtectionScope]::CurrentUser",
  "if ($mode -eq 'P') { $out = [System.Security.Cryptography.ProtectedData]::Protect($data, $entropy, $scope) }",
  "elseif ($mode -eq 'U') { $out = [System.Security.Cryptography.ProtectedData]::Unprotect($data, $entropy, $scope) }",
  "else { exit 2 }",
  "[Console]::Out.Write([Convert]::ToBase64String($out))",
].join("\n");

export type SpawnFn = (cmd: string, args: string[], opts: SpawnOptions) => ReturnType<typeof nodeSpawn>;

export function powershellArgs(): string[] {
  // -EncodedCommand takes UTF-16LE base64: no quoting, no interpolation, the script is constant
  return ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", Buffer.from(DPAPI_SCRIPT, "utf16le").toString("base64")];
}

export class DpapiProtector implements Protector {
  constructor(private readonly spawn: SpawnFn = nodeSpawn as SpawnFn, private readonly exe = "powershell.exe") {}

  protect(plain: string): Promise<string> {
    return this.run("P", Buffer.from(plain, "utf8")).then((b) => "dpapi:" + b.toString("base64"));
  }

  async unprotect(blob: string): Promise<string> {
    if (!blob.startsWith("dpapi:")) throw new ProtectorError("the stored key was not made by DPAPI");
    const out = await this.run("U", Buffer.from(blob.slice(6), "base64"));
    return out.toString("utf8");
  }

  private run(mode: "P" | "U", data: Buffer): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const child = this.spawn(this.exe, powershellArgs(), { windowsHide: true, shell: false, stdio: ["pipe", "pipe", "pipe"] });
      const out: Buffer[] = [];
      let done = false;
      const timer = setTimeout(() => {
        if (!done) {
          done = true;
          child.kill();
          reject(new ProtectorError("Windows did not encrypt the key in time"));
        }
      }, 20_000);
      child.stdout?.on("data", (c: Buffer) => out.push(c));
      child.stderr?.on("data", () => { /* PowerShell's words may hold nothing secret but are not needed */ });
      child.on("error", () => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        reject(new ProtectorError("PowerShell could not be started to protect the key"));
      });
      child.on("close", (code) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        const text = Buffer.concat(out).toString("ascii").trim();
        if (code !== 0 || !/^[A-Za-z0-9+/=]+$/.test(text)) {
          reject(new ProtectorError(mode === "P" ? "Windows could not encrypt the key" : "Windows could not decrypt the key (another user or computer?)"));
          return;
        }
        resolve(Buffer.from(text, "base64"));
      });
      child.stdin?.end(mode + " " + data.toString("base64") + "\n");
    });
  }
}

/**
 * For tests and non-Windows development only: AES-GCM under a key derived from a fixed
 * string. It is NOT protection - the real plugin uses DpapiProtector.
 */
export class FakeProtector implements Protector {
  calls: string[] = [];
  private readonly key = createHash("sha256").update("zigmon-streamdeck-fake-protector").digest();
  async protect(plain: string): Promise<string> {
    this.calls.push("protect");
    const iv = randomBytes(12);
    const c = createCipheriv("aes-256-gcm", this.key, iv);
    const enc = Buffer.concat([c.update(plain, "utf8"), c.final()]);
    return "fake:" + Buffer.concat([iv, c.getAuthTag(), enc]).toString("base64");
  }
  async unprotect(blob: string): Promise<string> {
    this.calls.push("unprotect");
    if (!blob.startsWith("fake:")) throw new ProtectorError("not a fake blob");
    const b = Buffer.from(blob.slice(5), "base64");
    const d = createDecipheriv("aes-256-gcm", this.key, b.subarray(0, 12));
    d.setAuthTag(b.subarray(12, 28));
    return Buffer.concat([d.update(b.subarray(28)), d.final()]).toString("utf8");
  }
}
