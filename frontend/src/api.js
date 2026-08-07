const API = "http://localhost:8000/api";

export const getForecastDay = async (date, refresh = false, view = "issued") => {
  const res = await fetch(`${API}/forecast_day?date=${date}&refresh=${refresh}&view=${view}`);
  if (!res.ok) throw new Error(`${res.status} - ${await res.text()}`);
  return res.json();
};

export const getOperationalForecast = async (asOfDate, refresh = false) => {
  const params = new URLSearchParams({ as_of_date: asOfDate, refresh: String(refresh) });
  const res = await fetch(`${API}/operational_forecast?${params}`);
  if (!res.ok) throw new Error(`${res.status} - ${await res.text()}`);
  return res.json();
};

export const getForecastTrend = async (days = 14) => {
  const res = await fetch(`${API}/forecast_trend?days=${days}`);
  if (!res.ok) throw new Error(`${res.status} - ${await res.text()}`);
  return res.json();
};

export const getStatus = async () => {
  const res = await fetch(`${API}/status`);
  return res.json();
};

export const API_BASE = API;
