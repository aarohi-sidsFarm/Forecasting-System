const API = "http://localhost:8000/api";
const pendingRequests = new Map();

const fetchJson = async (path) => {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${response.status} - ${await response.text()}`);
  return response.json();
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
