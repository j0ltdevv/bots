#!/usr/bin/env bun
// omp-tg — canal Telegram vers une session omp VIVANTE (celle de Tern).
//
// Transport : le bus de omp-dash (WebSocket 127.0.0.1:7317, role=browser).
// Chaque session omp ouverte dans Tern s'y enregistre comme backend
// "live:<sessionId>" ; on lui envoie {type:"prompt"} et on lit les évènements
// chat (agent_start → message_end → agent_end). Rien n'est tapé dans le TUI :
// pas de dialogue d'approbation validé par accident, pas de scraping d'écran.
//
// Usage:
//   omp-tg serve                boucle Telegram (systemd)
//   omp-tg --set-token <TOKEN>  enregistre le token et (re)démarre le service
//   omp-tg --backends           liste les sessions joignables
//   omp-tg --test "prompt"      envoie un prompt sur la session sélectionnée
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const CONF_DIR = join(homedir(), ".config", "omp-tg");
const CONF = join(CONF_DIR, "config.json");
const STATE = join(CONF_DIR, "state.json");
const LOG = join(CONF_DIR, "omp-tg.log");
const DASH_STATE = join(homedir(), ".cache", "omp-dash", "state.json");

interface Config {
  token: string;
  allowed_user_id: number;
  backend: string;      // "" = auto (session live la plus récente)
  cwd: string;          // cwd du panneau créé en secours
  turn_timeout: number; // secondes
}

const DEFAULTS: Config = {
  token: "",
  allowed_user_id: 0,
  backend: "",
  cwd: homedir(),
  turn_timeout: 600,
};

function log(msg: string): void {
  mkdirSync(CONF_DIR, { recursive: true });
  appendFileSync(LOG, `${new Date().toISOString()} ${msg}\n`);
}

function readJson<T>(path: string, fallback: T): T {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return fallback;
  }
}

function writeJson(path: string, data: unknown): void {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 1));
}

function conf(): Config {
  return { ...DEFAULTS, ...readJson<Partial<Config>>(CONF, {}) };
}

/* ------------------------------------------------------------------ dash bus */

interface BackendInfo {
  id: string;
  kind: "dedicated" | "live";
  label: string;
  alive: boolean;
  model?: string;
  provider?: string;
  cwd?: string;
}

interface DashState { pid: number; port: number; token: string }

class Dash {
  private ws: WebSocket | null = null;
  backends = new Map<string, BackendInfo>();
  private waiters = new Map<string, { resolve: (t: string) => void; text: string[] }>();
  private connected: Promise<void>;
  private done!: () => void;
  private fail!: (err: Error) => void;

  constructor() {
    this.connected = new Promise((res, rej) => { this.done = res; this.fail = rej; });
    void this.loop();
  }

  private readState(): DashState | null {
    const st = readJson<DashState | null>(DASH_STATE, null);
    return st && st.port && st.token ? st : null;
  }

  private async loop(): Promise<void> {
    for (;;) {
      const st = this.readState();
      if (!st) {
        this.fail(new Error("omp-dash ne tourne pas (~/.cache/omp-dash/state.json absent)"));
        await Bun.sleep(3000);
        continue;
      }
      await new Promise<void>((resolve) => {
        const ws = new WebSocket(`ws://127.0.0.1:${st.port}/ws?token=${st.token}&role=browser`);
        this.ws = ws;
        let settled = false;
        ws.addEventListener("open", () => { log("dash connecté"); this.done(); });
        ws.addEventListener("message", (ev) => this.onMessage(String(ev.data)));
        ws.addEventListener("close", () => {
          this.ws = null;
          if (!settled) { settled = true; resolve(); }
        });
        ws.addEventListener("error", () => {
          if (!settled) { settled = true; this.fail(new Error("dash WS error")); resolve(); }
        });
      });
      await Bun.sleep(2000);
    }
  }

  ready(): Promise<void> { return this.connected; }

  send(cmd: Record<string, unknown>): void {
    if (!this.ws) throw new Error("dash non connecté");
    this.ws.send(JSON.stringify(cmd));
  }

  private onMessage(raw: string): void {
    let msg: any;
    try { msg = JSON.parse(raw); } catch { return; }
    if (msg.type === "backends") {
      this.backends = new Map<string, BackendInfo>(
        (msg.backends as BackendInfo[]).map((b) => [b.id, b]),
      );
      return;
    }
    if (msg.type !== "chat") return;
    const waiter = this.waiters.get(msg.backend);
    if (!waiter) return;
    const ev = msg.event ?? {};
    if (ev.type === "message_end" && ev.message?.role === "assistant") {
      const text = (ev.message.content ?? [])
        .filter((p: any) => p?.type === "text")
        .map((p: any) => p.text)
        .join("")
        .trim();
      if (text) waiter.text.push(text);
    }
    if (ev.type === "agent_end") {
      this.waiters.delete(msg.backend);
      waiter.resolve(waiter.text.join("\n\n").trim());
    }
  }

  promptAndWait(backend: string, text: string, timeoutSec: number): Promise<string> {
    return new Promise((resolve, reject) => {
      const entry = { resolve, text: [] as string[] };
      this.waiters.set(backend, entry);
      const timer = setTimeout(() => {
        this.waiters.delete(backend);
        resolve(entry.text.join("\n\n").trim() + "\n\n[timeout]");
      }, timeoutSec * 1000);
      const done = entry.resolve;
      entry.resolve = (t: string) => { clearTimeout(timer); done(t); };
      try {
        this.send({ type: "prompt", backend, text, delivery: "followUp" });
      } catch (err) {
        clearTimeout(timer);
        this.waiters.delete(backend);
        reject(err as Error);
      }
    });
  }

  abort(backend: string): void {
    this.send({ type: "abort", backend });
  }

  live(): BackendInfo[] {
    return [...this.backends.values()]
      .filter((b) => b.kind === "live" && b.alive)
      .sort((a, b) => (a.id < b.id ? 1 : -1)); // sessionId UUIDv7 : plus récent d'abord
  }
}

/* -------------------------------------------------------------- Tern fallback */

function tern(args: string[]): { ok: boolean; out: string } {
  const env = { ...process.env, HOME: homedir() };
  delete (env as any).TERN_PANE;
  const res = Bun.spawnSync(["tern", ...args], { env, stdout: "pipe", stderr: "pipe" });
  return { ok: res.exitCode === 0, out: `${res.stdout}${res.stderr}`.trim() };
}

function createPane(cfg: Config): string | null {
  const launch = ["--cwd", cfg.cwd, "--", "omp", "--auto-approve", "--hide-thinking"];
  let r = tern(["new", "tab", "phone", ...launch]);
  if (!r.ok) r = tern(["new", "session", "phone", ...launch]);
  if (!r.ok) {
    log(`création du panneau impossible: ${r.out}`);
    return null;
  }
  log("panneau omp créé dans Tern (session phone)");
  return r.out;
}

/* --------------------------------------------------------------------- picker */

function pick(dash: Dash, cfg: Config): BackendInfo | null {
  const live = dash.live();
  if (!live.length) return null;
  const saved = readJson<{ backend?: string }>(STATE, {}).backend;
  const wanted = cfg.backend || saved || "";
  const hit = live.find((b) => b.id === wanted);
  if (hit) return hit;
  const sameCwd = live.find((b) => b.cwd === cfg.cwd);
  return sameCwd ?? live[0];
}

function describe(backends: BackendInfo[], current?: string): string {
  if (!backends.length) return "Aucune session omp vivante dans Tern.";
  return backends
    .map((b, i) => `${b.id === current ? "▶" : " "} ${i + 1}. ${b.cwd ?? "?"} · ${b.model ?? "?"}${b.id === current ? " (active)" : ""}`)
    .join("\n");
}

/* ------------------------------------------------------------------- Telegram */

class Tg {
  constructor(private token: string) {}
  private base = () => `${process.env.OMP_TG_API ?? "https://api.telegram.org"}/bot${this.token}`;

  async call(method: string, params: Record<string, unknown>, timeout = 45): Promise<any> {
    const res = await fetch(`${this.base()}/${method}`, {
      method: "POST",
      body: new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ),
      signal: AbortSignal.timeout(timeout * 1000),
    });
    return res.json();
  }

  async send(chat_id: number, text: string, reply_to?: number): Promise<void> {
    const body = text.trim() || "(vide)";
    for (let i = 0; i < body.length; i += 4000) {
      const params: Record<string, unknown> = {
        chat_id,
        text: body.slice(i, i + 4000),
        disable_web_page_preview: "true",
      };
      if (reply_to && i === 0) params.reply_to_message_id = reply_to;
      try {
        await this.call("sendMessage", params);
      } catch (err) {
        log(`sendMessage échoué: ${err}`);
      }
    }
  }

  async typing(chat_id: number): Promise<void> {
    try { await this.call("sendChatAction", { chat_id, action: "typing" }, 15); } catch {}
  }

  async updates(offset: number): Promise<any[]> {
    try {
      const res = await this.call("getUpdates", { offset, timeout: 25 }, 40);
      if (!res.ok) { log(`getUpdates: ${JSON.stringify(res).slice(0, 200)}`); return []; }
      return res.result ?? [];
    } catch (err) {
      log(`getUpdates: ${err}`);
      await Bun.sleep(3000);
      return [];
    }
  }
}

/* ----------------------------------------------------------------------- serve */

async function serve(): Promise<number> {
  const cfg = conf();
  if (!cfg.token) {
    log("token manquant — omp-tg --set-token <TOKEN>");
    console.error("token manquant: omp-tg --set-token <TOKEN>");
    return 0;
  }
  const tg = new Tg(cfg.token);
  const dash = new Dash();
  await dash.ready().catch(() => {});
  let allowed = Number(cfg.allowed_user_id || 0);
  let offset = Number(readJson<{ offset?: number }>(STATE, {}).offset ?? 0);
  log(`démarrage (allowed=${allowed}, backend=${cfg.backend || "auto"})`);

  for (;;) {
    const updates = await tg.updates(offset);
    for (const upd of updates) {
      offset = Number(upd.update_id) + 1;
      writeJson(STATE, { ...readJson(STATE, {}), offset });
      const msg = upd.message ?? upd.edited_message;
      if (!msg?.text) continue;
      const user = Number(msg.from?.id ?? 0);
      const chat = Number(msg.chat.id);
      const text = String(msg.text).trim();
      if (allowed && user !== allowed) {
        log(`refus utilisateur ${user}`);
        await tg.send(chat, "Non autorisé.");
        continue;
      }
      if (!allowed) {
        allowed = user;
        writeJson(CONF, { ...cfg, allowed_user_id: user });
        log(`premier expéditeur accepté: ${user}`);
      }
      const [head, ...rest] = text.split(/\s+/);
      const cmd = head.toLowerCase();

      if (cmd === "/start" || cmd === "/help") {
        await tg.send(chat,
          "Envoie un message : il part dans la session omp vivante de Tern.\n" +
          "/backends liste les sessions · /use <n> en choisit une\n" +
          "/abort coupe le tour en cours · /status session active");
        continue;
      }

      try {
        if (cmd === "/backends" || cmd === "/status") {
          await dash.ready().catch(() => {});
          const cur = pick(dash, cfg);
          await tg.send(chat, describe(dash.live(), cur?.id));
          continue;
        }
        if (cmd === "/use") {
          await dash.ready().catch(() => {});
          const live = dash.live();
          const n = Number(rest[0]);
          const target = live[n - 1];
          if (!target) { await tg.send(chat, `Numéro invalide.\n${describe(live)}`); continue; }
          cfg.backend = target.id;
          writeJson(CONF, cfg);
          writeJson(STATE, { ...readJson(STATE, {}), backend: target.id });
          await tg.send(chat, `Session active : ${target.cwd ?? target.id}`);
          continue;
        }
        if (cmd === "/abort") {
          const cur = pick(dash, cfg);
          if (!cur) { await tg.send(chat, "Aucune session vivante."); continue; }
          dash.abort(cur.id);
          await tg.send(chat, "Abort envoyé.");
          continue;
        }

        let backend = pick(dash, cfg);
        if (!backend) {
          createPane(cfg);
          await Bun.sleep(4000);
          backend = pick(dash, cfg);
        }
        if (!backend) {
          await tg.send(chat, "Aucune session omp joignable : ouvre un bloc omp dans Tern.");
          continue;
        }
        await tg.typing(chat);
        const slow = setInterval(() => void tg.typing(chat), 15000);
        const reply = await dash.promptAndWait(backend.id, text, cfg.turn_timeout);
        clearInterval(slow);
        await tg.send(chat, reply || "(aucune sortie)");
      } catch (err) {
        log(`tour échoué: ${err}`);
        await tg.send(chat, `Erreur: ${err}`);
      }
    }
  }
}

/* ------------------------------------------------------------------------- cli */

const argv = process.argv.slice(2);

if (argv[0] === "--set-token") {
  const token = (argv[1] ?? "").trim();
  if (!token) { console.error("usage: omp-tg --set-token <TOKEN>"); process.exit(2); }
  writeJson(CONF, { ...conf(), token });
  Bun.spawnSync(["chmod", "600", CONF]);
  Bun.spawnSync(["systemctl", "--user", "enable", "omp-tg.service"]);
  Bun.spawnSync(["systemctl", "--user", "restart", "omp-tg.service"]);
  console.log("token enregistré, service activé.");
  process.exit(0);
}

if (argv[0] === "--backends") {
  const dash = new Dash();
  await dash.ready();
  await Bun.sleep(500);
  console.log(describe(dash.live(), pick(dash, conf())?.id));
  process.exit(0);
}

if (argv[0] === "--test") {
  const cfg = conf();
  const dash = new Dash();
  await dash.ready();
  await Bun.sleep(1000);
  const backend = pick(dash, cfg);
  if (!backend) { console.error("aucune session vivante"); process.exit(1); }
  console.log(`session ${backend.id} (${backend.cwd})`);
  console.log(await dash.promptAndWait(backend.id, argv.slice(1).join(" ") || "Réponds exactement: PONG", cfg.turn_timeout));
  process.exit(0);
}

process.exit(await serve());
