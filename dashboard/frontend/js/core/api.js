export function apiBase() {
  return document.getElementById("apiBase").value.replace(/\/$/, "");
}

export async function requestJson(path, options) {
  const res = await fetch(apiBase() + path, options);
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  return { ok: res.ok, status: res.status, data };
}
