#pragma once
class Preferences {
 public:
  bool begin(const char*, bool) { return true; }
  bool getBool(const char*, bool d) { return d; }
  size_t putBool(const char*, bool) { return 1; }
};
