/**
 * Speech-to-text: hosted URL (any size) or a local file (raw body, up to ~4.5 MB).
 *
 *   npm run listen -- https://dpgr.am/spacewalk.wav
 *   npm run listen -- ./meeting.wav
 */
import { readFile } from "node:fs/promises";
import { DeepgramX402Client } from "./x402.js";

const source = process.argv[2] ?? "https://dpgr.am/spacewalk.wav";
const params = { model: "nova-3", smart_format: "true" };
const client = new DeepgramX402Client();

const paid = /^https?:\/\//.test(source)
  ? await client.post("/v1/listen", params, JSON.stringify({ url: source }), "application/json")
  : await client.post("/v1/listen", params, await readFile(source), contentTypeFor(source));

if (!paid.response.ok) throw new Error(`Deepgram ${paid.response.status}: ${await paid.response.text()}`);
const result = (await paid.response.json()) as {
  results: { channels: { alternatives: { transcript: string }[] }[] };
};
console.log(result.results.channels[0].alternatives[0].transcript);
console.error(`paid $${paid.amountUsd} (payment ${paid.paymentId})`);

function contentTypeFor(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const types: Record<string, string> = { mp3: "audio/mpeg", flac: "audio/flac", ogg: "audio/ogg", wav: "audio/wav" };
  return types[ext] ?? "audio/wav";
}
