import { describe, it, expect } from "vitest";
import { telegramDeepLink, imessagePairLink, smsPairLink } from "./deeplinks";

describe("telegramDeepLink", () => {
  it("constructs a valid Telegram deep link", () => {
    const result = telegramDeepLink("hermes_bot", "abc123token");
    expect(result).toBe("https://t.me/hermes_bot?start=abc123token");
  });

  it("handles tokens with special url-safe base64 chars", () => {
    const result = telegramDeepLink("bot", "a-b_c");
    expect(result).toBe("https://t.me/bot?start=a-b_c");
  });

  it("handles empty token", () => {
    const result = telegramDeepLink("bot", "");
    expect(result).toBe("https://t.me/bot?start=");
  });
});

describe("imessagePairLink", () => {
  it("constructs a valid imessage pair link", () => {
    const result = imessagePairLink("+15551234567", "ABC123");
    expect(result).toBe(
      `imessage://${encodeURIComponent("+15551234567")}?body=${encodeURIComponent("pair ABC123")}`,
    );
  });

  it("encodes the phone number and pair code", () => {
    const result = imessagePairLink("+1 555 123", "XYZ");
    expect(result).toContain("imessage://");
    expect(result).toContain("body=pair%20XYZ");
  });

  it("encodes special characters in number", () => {
    const result = imessagePairLink("+15551234567", "CODE");
    expect(result).toBe("imessage://%2B15551234567?body=pair%20CODE");
  });
});

describe("smsPairLink", () => {
  it("constructs a valid sms pair link", () => {
    const result = smsPairLink("+15551234567", "ABC123");
    expect(result).toBe(
      `sms:${encodeURIComponent("+15551234567")}?body=${encodeURIComponent("pair ABC123")}`,
    );
  });

  it("uses sms: scheme (not imessage://)", () => {
    const result = smsPairLink("+15550000000", "TEST");
    expect(result.startsWith("sms:")).toBe(true);
    expect(result).not.toContain("imessage");
  });

  it("encodes the body with pair prefix", () => {
    const result = smsPairLink("+1", "Z9K");
    expect(result).toContain("body=pair%20Z9K");
  });
});
