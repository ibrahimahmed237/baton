// M0b spike: a test plugin for OpenCode. Throwaway code.
//
// Two questions: can a plugin give the agent extra text when the user sends a
// message, and does OpenCode say when a reply finishes and in which chat?
// Every call is logged to .baton-spike/opencode-hook-log.jsonl. A prompt that
// contains "hook test" gets a codeword attached: KIWI-6.
//
// Registered for this folder only, as .opencode/plugins/baton-spike.js.
import { appendFileSync, mkdirSync } from "node:fs"

const DIR = "/Users/ibrahimahmed/Desktop/projects/baton/.baton-spike"
const LOG = DIR + "/opencode-hook-log.jsonl"
const QUIET = new Set(["message.part.updated", "message.part.delta", "lsp.client.diagnostics", "file.watcher.updated"])

function log(entry) {
  try {
    mkdirSync(DIR, { recursive: true })
    appendFileSync(LOG, JSON.stringify({ at: new Date().toISOString(), ...entry }) + "\n")
  } catch {}
}

function partId() {
  const value = (BigInt(Date.now()) * 0x1000n + 0xfffn) & 0xffffffffffffn
  const tail = Array.from({ length: 14 }, () => "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 62)]).join("")
  return "prt_" + value.toString(16).padStart(12, "0") + tail
}

export const BatonSpike = async ({ directory }) => {
  log({ event: "plugin loaded", directory })
  return {
    "chat.message": async (input, output) => {
      const text = output.parts.filter((part) => part.type === "text").map((part) => part.text).join(" ")
      const attach = text.toLowerCase().includes("hook test")
      log({ event: "chat.message", input, message: output.message, parts: output.parts.map((part) => ({ ...part, text: undefined })), attach })
      if (attach && output.parts.length) {
        const first = output.parts[0]
        output.parts.push({
          id: partId(), sessionID: first.sessionID, messageID: first.messageID, type: "text", synthetic: true,
          text: "<baton-catch-up>Baton spike, given with this message. The codeword is KIWI-6.</baton-catch-up>",
        })
      }
    },
    event: async ({ event }) => {
      if (QUIET.has(event.type)) return
      const p = event.properties || {}
      log({ event: event.type, sessionID: p.sessionID || p.info?.sessionID || p.info?.id, status: p.status, role: p.info?.role, finish: p.info?.finish })
    },
  }
}
