// The old standalone pages are now tabs of the one-page Trading desk (UR1).
// Old bookmarks and deep links keep working: the query string (e.g. an exact
// evidence-package or record link) is kept and the matching tab is opened.
import { tabFromHash } from "./desk-state.mjs";

export function legacyTarget(tab, search = "", hash = "") {
  const fromHash = tabFromHash(hash);
  const target = hash && fromHash !== "today" ? fromHash : tabFromHash(`#${tab}`);
  return `./index.html${search}#${target}`;
}

if (typeof document !== "undefined") {
  location.replace(legacyTarget(document.documentElement.dataset.deskTab, location.search, location.hash));
}
