import { sha256 } from "@noble/hashes/sha2.js";
// Named local HTTP origins do not expose Web Crypto; byte integrity is still mandatory.
export function digestHex(data: Uint8Array): string {
  return Array.from(sha256(data), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}
