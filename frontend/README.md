# Forecast dashboard

React/Vite dashboard for reviewing and sharing city/SKU procurement forecasts.

## Local development

```powershell
npm install
npm run dev
```

The frontend reads the backend URL from `VITE_API_URL` and otherwise uses
`http://127.0.0.1:8000`.

## Validation

```powershell
npm run lint
npm run build
```

The production build is generated in `dist/` and is intentionally ignored by
Git.
