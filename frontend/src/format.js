// Formatting and date helpers shared by the Forecast and Trends views.

export const CITY_NAMES = {
  HYD: "Hyderabad",
  VGA: "Vijayawada",
  BLR: "Bengaluru",
  PNQ: "Pune",
};

// Order of cities on screen and in shared text.
export const CITY_ORDER = ["HYD", "BLR", "PNQ", "VGA"];

export const fmt = (value) => Number(value ?? 0).toLocaleString("en-IN");
export const fmtSigned = (value) => `${Number(value) > 0 ? "+" : ""}${fmt(value)}`;
export const fmtPct = (value) => `${Number(value ?? 0).toFixed(1)}%`;
export const fmtSignedPct = (value) => `${Number(value) > 0 ? "+" : ""}${fmtPct(value)}`;
export const cityName = (city) => CITY_NAMES[city] ?? city;
export const cityRank = (city) => {
  const index = CITY_ORDER.indexOf(city);
  return index === -1 ? CITY_ORDER.length : index;
};

export const isoInIndia = (date) => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(date);

export const todayInIndia = () => isoInIndia(new Date());

export const shiftDate = (iso, days) => {
  const date = new Date(`${iso}T12:00:00+05:30`);
  date.setUTCDate(date.getUTCDate() + days);
  return isoInIndia(date);
};

export const daysBetween = (fromIso, toIso) => Math.round(
  (new Date(`${toIso}T12:00:00+05:30`) - new Date(`${fromIso}T12:00:00+05:30`)) / 86400000,
);

// One date format everywhere: "Mon, 26 Oct" (year only where it matters).
export const formatDate = (iso, withYear = false) => {
  const parts = new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).formatToParts(new Date(`${iso}T12:00:00+05:30`));
  const part = (type) => parts.find((p) => p.type === type)?.value;
  return `${part("weekday")}, ${part("day")} ${part("month")}${withYear ? ` ${part("year")}` : ""}`;
};

// "26 Oct" or "26 Oct 2026", without the weekday, for ranges and axes.
export const formatDay = (iso, withYear = false) => formatDate(iso, withYear).split(", ")[1];

export const csvCell = (value) => {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

export const downloadCsv = (fileName, header, rows) => {
  const csv = [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
  // The byte-order mark makes Excel read the file as UTF-8.
  const href = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking straight away cancels the download in Firefox and Safari.
  setTimeout(() => URL.revokeObjectURL(href), 1000);
};
