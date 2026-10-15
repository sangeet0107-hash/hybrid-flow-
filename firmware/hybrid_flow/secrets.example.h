// Copy this file to secrets.h and fill in your values.
// secrets.h is in .gitignore so your Wi-Fi password never reaches GitHub.
#pragma once

#define WIFI_SSID     "your-wifi-name"
#define WIFI_PASSWORD "your-wifi-password"

// Realtime Database URL from the Firebase console, without a trailing slash,
// e.g. "https://hybrid-flow-demo-default-rtdb.asia-southeast1.firebasedatabase.app"
#define FIREBASE_DB_URL "https://your-project-default-rtdb.firebaseio.com"

// Optional: a database secret or ID token. Leave empty while the database
// uses the demo rules in backend/firebase/database.rules.json.
#define FIREBASE_AUTH ""
