/**
 * Text-to-speech with Flux TTS (/v2/speak) or Aura-2 (/v1/speak).
 *
 *   npm run speak -- "Your appointment is confirmed for 3pm tomorrow." flux-haley-en
 *   npm run speak -- "Hello from Deepgram." aura-2-thalia-en
 */
import { writeFile } from "node:fs/promises";
import { DeepgramX402Client } from "./x402.js";

const text = process.argv[2] ?? "Hello from Deepgram.";
const model = process.argv[3] ?? "flux-haley-en";
const path = model.startsWith("flux-") ? "/v2/speak" : "/v1/speak";

const paid = await new DeepgramX402Client().post(path, { model }, JSON.stringify({ text }), "application/json");
if (!paid.response.ok) throw new Error(`Deepgram ${paid.response.status}: ${await paid.response.text()}`);
const audio = Buffer.from(await paid.response.arrayBuffer());
await writeFile("speech.mp3", audio);
console.log(`wrote speech.mp3 (${audio.length} bytes); paid $${paid.amountUsd} (payment ${paid.paymentId})`);
