const API = "http://localhost:8000/api";

const fetchJson = async (path) => {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${response.status} - ${await response.text()}`);
  return response.json();
};

export const getOperationalForecast = async (targetDate, refresh = false) => {
  const params = new URLSearchParams({ target_date: targetDate, refresh: String(refresh) });
  return fetchJson(`/operational_forecast?${params}`);
};

export const getStatus = () => fetchJson("/status");
