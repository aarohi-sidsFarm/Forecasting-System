const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
const pendingRequests = new Map();

const fetchJson = async (path) => {
  let response;
  try {
    response = await fetch(`${API}${path}`);
  } catch {
    // Render answers without CORS headers while it deploys or wakes up, so
    // the browser reports only a network failure.
    const error = new Error("The forecast server is not reachable right now.");
    error.code = "unreachable";
    throw error;
  }
  const payload = await response.json().catch(() => null);
  if (response.status === 202 && payload?.status === "refresh_in_progress") {
    const error = new Error(
      `${payload.detail}. Retry in about ${payload.retry_after_seconds ?? 15} seconds; any frozen forecast remains unchanged.`,
    );
    error.code = "refresh_in_progress";
    throw error;
  }
  if (!response.ok) {
    const detail = payload?.detail ?? JSON.stringify(payload);
    const error = new Error(`${response.status} - ${detail}`);
    if ([502, 503, 504].includes(response.status)) error.code = "unreachable";
    throw error;
  }
  return payload;
};

export const getOperationalForecast = async (targetDate, refresh = false) => {
  const params = new URLSearchParams({ target_date: targetDate, refresh: String(refresh) });
  const path = `/operational_forecast?${params}`;
  if (pendingRequests.has(path)) return pendingRequests.get(path);
  const request = fetchJson(path).finally(() => pendingRequests.delete(path));
  pendingRequests.set(path, request);
  return request;
};

export const getStatus = () => fetchJson("/status");
