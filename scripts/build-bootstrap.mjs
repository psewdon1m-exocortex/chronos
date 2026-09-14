import { createPublicKey } from "node:crypto";
import fs from "node:fs";

const [templatePath, publicKeyPath, outputPath, version] = process.argv.slice(2);
if (!templatePath || !publicKeyPath || !outputPath || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version ?? "")) throw new Error("Usage: build-bootstrap.mjs <template> <public-key.pem> <output> <version>");
const publicPem = fs.readFileSync(publicKeyPath, "utf8");
const key = createPublicKey(publicPem);
if (key.asymmetricKeyType !== "rsa" || (key.asymmetricKeyDetails?.modulusLength ?? 0) < 3072) throw new Error("Head bootstrap requires RSA-3072 public trust");
if (/PRIVATE KEY/.test(publicPem)) throw new Error("Refusing to embed private key material");
const template = fs.readFileSync(templatePath, "utf8");
for (const value of ["__HEAD_BOOTSTRAP_RELEASE_VERSION__", "__HEAD_BOOTSTRAP_PUBLIC_KEY_BASE64__"]) if (template.split(value).length !== 2) throw new Error(`Expected exactly one ${value}`);
const output = template.replace("__HEAD_BOOTSTRAP_RELEASE_VERSION__", version).replace("__HEAD_BOOTSTRAP_PUBLIC_KEY_BASE64__", Buffer.from(publicPem).toString("base64"));
if (output.includes("__HEAD_BOOTSTRAP_") || /PRIVATE KEY/.test(output)) throw new Error("Unsafe generated bootstrap");
fs.writeFileSync(outputPath, output, { mode: 0o755 });
