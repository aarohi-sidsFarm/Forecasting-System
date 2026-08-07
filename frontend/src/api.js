const API = "http://localhost:8000/api";

const fetchJson = async (path) => {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${response.status} - ${await response.text()}`);
  return response.json();
};

export const getOperationalForecast = async (asOfDate, refresh = false) => {
  const params = new URLSearchParams({ as_of_date: asOfDate, refresh: String(refresh) });
  return fetchJson(`/operational_forecast?${params}`);
};

export const getStatus = () => fetchJson("/status");
