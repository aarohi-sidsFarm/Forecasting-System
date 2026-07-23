const API = "http://localhost:8000/api";

export const getForecastDay = async (date, refresh = false) => {
  const res = await fetch(`${API}/forecast_day?date=${date}&refresh=${refresh}`);
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
