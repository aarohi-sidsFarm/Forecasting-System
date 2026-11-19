// Logo, product name and the view tabs, shared by both views' headers.
export default function Brand({ children }) {
  return (
    <div className="header-left">
      <div className="brand">
        <img className="brand-logo" src="/apple-touch-icon.png" alt="Sid's Farm" width="28" height="28" />
        <span className="brand-title">Order Forecasting</span>
      </div>
      {children}
    </div>
  );
}
