// Deep-link builders for the connect wizard (design §7). Telegram's deep-link is
// computed server-side by createPairingToken (returns deepLink); these are the
// client-side fallbacks + the iMessage link (which the server can't build because
// it needs the shared Sendblue number, exposed as a public env var).

export function telegramDeepLink(botUsername: string, token: string): string {
  return `https://t.me/${botUsername}?start=${token}`;
}

// imessage://<number>?body=pair%20<code> — opens Messages prefilled to the shared
// number with "pair <code>". sms: fallback is offered separately in the UI.
export function imessagePairLink(toNumber: string, code: string): string {
  const body = encodeURIComponent(`pair ${code}`);
  return `imessage://${encodeURIComponent(toNumber)}?body=${body}`;
}

export function smsPairLink(toNumber: string, code: string): string {
  const body = encodeURIComponent(`pair ${code}`);
  return `sms:${encodeURIComponent(toNumber)}?body=${body}`;
}

// Public env (safe to expose): the shared iMessage number + the bot username.
export const IMESSAGE_NUMBER = process.env.NEXT_PUBLIC_IMESSAGE_NUMBER ?? "";
export const TELEGRAM_BOT_USERNAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME ?? "";
