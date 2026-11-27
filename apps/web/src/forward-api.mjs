// Read-only client for the local forward-stage research API (E2f2):
//   GET /api/research/forward/verdicts           imported study verdicts (C-109)
//   GET /api/research/forward/{strategy}?version  frozen candidate's SIMULATED
//                                                 forward record and stage
// Nothing here writes, refreshes or places anything.
import { API_ORIGIN } from "./runtime-config.mjs";

const BASE = "/api/research/forward";
const CODE = /^[A-Z][A-Z0-9_]{2,63}$/;
const SLUG = /^[a-z0-9-]{1,64}$/;
const VERSION = /^[1-9]\d{0,5}$/;

// A failed read keeps a safe message and the API's problem code (allowlisted
// shape only; server details are never shown).
function forwardError(status, code) {
  const message = status === 404
    ? "This strategy has no registered forward record."
    : status === 422
      ? "The API could not build this forward record from the stored snapshots."
      : status >= 500
        ? "The local research API or its storage is unavailable."
        : "The local research API rejected this request.";
  const error = new Error(code ? `${message} [${code}]` : `${message} [HTTP ${status}]`);
  error.status = status;
  error.code = code ?? null;
  return error;
}

async function get(fetcher, path) {
  let response;
  try {
    response = await fetcher(`${API_ORIGIN}${BASE}${path}`, {
      method: "GET", credentials: "omit", cache: "no-store", headers: { Accept: "application/json" },
    });
  } catch {
    throw new Error("The local research API is unreachable.");
  }
  if (!response.ok) {
    let code = null;
    try {
      const problem = await response.json();
      if (typeof problem?.code === "string" && CODE.test(problem.code)) code = problem.code;
    } catch {
      // Unreadable problem bodies keep the generic message.
    }
    throw forwardError(response.status, code);
  }
  try {
    return await response.json();
  } catch {
    throw new Error("The local research API returned an unreadable response.");
  }
}

export async function readForwardVerdicts(fetcher = globalThis.fetch) {
  const page = await get(fetcher, "/verdicts");
  if (!page || !Array.isArray(page.items)) throw new Error("The verdicts response is not in the expected form.");
  return page.items;
}

export async function readForwardStage(fetcher, strategy, version) {
  if (!SLUG.test(String(strategy)) || !VERSION.test(String(version))) {
    throw new Error("Choose a registered forward strategy and version.");
  }
  return get(fetcher, `/${encodeURIComponent(strategy)}?${new URLSearchParams({ version: String(version) })}`);
}
