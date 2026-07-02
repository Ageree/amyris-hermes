import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { patchSpectrumTs } from "../patch-spectrum-mixed-attachments.mjs";

const fixture = `var rebuildFromAppleMessage = async (client, base, message, messageGuidStr) => {
  const attachments = messageAttachments(message);
  if (attachments.length === 1) {
    const info = attachments[0];
    return buildAttachmentMessage(client, base, info, messageGuidStr, 0);
  }
  if (attachments.length > 1) {
    const items = [];
    for (let i = 0; i < attachments.length; i++) {
      items.push(await buildAttachmentMessage(
          client,
          base,
          attachments[i],
          formatChildId(i, messageGuidStr),
          i,
          messageGuidStr
      ));
    }
    return {
      ...base,
      id: messageGuidStr,
      content: asProviderGroup(items)
    };
  }
  if (getBalloonBundleId(message) === URL_BALLOON_BUNDLE_ID) {
    return base;
  }
  const text2 = message.content.text;
  return {
    ...base,
    content: asText(text2)
  };
};

var toInboundMessages = async (client, cache, event, base, messageGuidStr) => {
  const attachments = messageAttachments(event.message);
  if (attachments.length === 1) {
    const info = attachments[0];
    const msg2 = await buildAttachmentMessage(
      client,
      base,
      info,
      messageGuidStr,
      0
    );
    cacheMessage(cache, msg2);
    return [msg2];
  }
  if (attachments.length > 1) {
    const items = [];
    for (let i = 0; i < attachments.length; i++) {
      items.push(await buildAttachmentMessage(
          client,
          base,
          attachments[i],
          formatChildId(i, messageGuidStr),
          i,
          messageGuidStr
      ));
    }
    const parent = {
      ...base,
      id: messageGuidStr,
      content: asProviderGroup(items)
    };
    cacheMessage(cache, parent);
    return [parent];
  }
  const text2 = event.message.content.text;
  const msg = {
    ...base,
    content: asText(text2)
  };
  cacheMessage(cache, msg);
  return [msg];
};
`;

test("patchSpectrumTs preserves text in mixed attachment events", () => {
  const root = mkdtempSync(path.join(tmpdir(), "photon-sidecar-patch-"));
  try {
    const dist = path.join(root, "node_modules", "spectrum-ts", "dist");
    mkdirSync(dist, { recursive: true });
    const chunk = path.join(dist, "chunk-imessage.js");
    writeFileSync(chunk, fixture, "utf8");

    const result = patchSpectrumTs(root);
    const patched = readFileSync(chunk, "utf8");

    assert.equal(result.patched, true);
    assert.match(patched, /Hermes patch: Preserve mixed text/);
    assert.match(patched, /content: asProviderGroup\(\[textMsg, msg2\]\)/);
    assert.match(patched, /items.unshift/);

    const second = patchSpectrumTs(root);
    assert.equal(second.patched, false);
    assert.equal(second.reason, "already patched");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
