import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";

const failureNote = __BATON_FAILURE_NOTE__;

// Hook commands fail closed; payload identities travel as arguments, never shell text.
const run = args => new Promise(resolve => {
  execFile("baton", args, { timeout: 2000, maxBuffer: 1048576 },
    (error, stdout) => {
      if (error) { console.error(failureNote); resolve(""); return; }
      resolve(stdout);
    });
});
export const Baton = async () => ({
  "chat.message": async (input, output) => {
    const sessionID = input.sessionID || output.message?.sessionID;
    const messageID = output.message?.id;
    if (!sessionID || !messageID) return;
    const text = await run(["catch-up", "--tool", "opencode", "--chat", sessionID,
      "--turn-id", messageID]);
    if (text.trim()) output.parts.push({
      id: "prt_" + ((BigInt(Date.now()) * 0x1000n + 0xfffn) & 0xffffffffffffn)
        .toString(16).padStart(12, "0") + randomBytes(14).toString("hex").slice(0, 14),
      sessionID, messageID, type: "text", synthetic: true, text,
    });
  },
  event: async ({ event }) => {
    const p = event.properties || {};
    const sessionID = p.sessionID || p.info?.sessionID;
    const status = p.status?.type;
    const name = event.type === "session.idle" ? "idle" : status;
    if (sessionID && (event.type === "session.idle" || event.type === "session.status")
        && (name === "busy" || name === "idle")) {
      await run(["notify", "--tool", "opencode", "--chat", sessionID, "--event", name]);
    }
  },
});
