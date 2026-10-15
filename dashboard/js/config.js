/*
 * Dashboard settings. Leave FIREBASE_DB_URL empty to open in Demo mode.
 * You can also connect from the page (Data source button) or with a link:
 *   index.html?db=https://<project>-default-rtdb.<region>.firebasedatabase.app&device=hf-001
 */
window.HF_CONFIG = {
  FIREBASE_DB_URL: "",
  DEVICE_ID: "hf-001",
  FIREBASE_AUTH: "",
  GRID_TARIFF_RS_PER_KWH: 7.0,   // used only for the "grid cost avoided" estimate
  HISTORY_MINUTES: 6             // how much history the charts keep
};
