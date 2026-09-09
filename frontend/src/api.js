const API = "http://localhost:8000/api";
const pendingRequests = new Map();

const fetchJson = async (path) => {
  const response = await fetch(`${API}${path}`);
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
    throw new Error(`${response.status} - ${detail}`);
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
