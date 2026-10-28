# PC unit tests for the firmware control logic.
#   make        build and run the scenario tests
#   make syntax compile-check the whole sketch against host stand-ins for the Arduino APIs
#   make clean  remove build output
CXX ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Werror -O1
PYTHON ?= python3
SRC = ../../firmware/hybrid_flow/control_logic.cpp

all: run

scenarios.inc: ../scenarios.json gen_scenarios.py
	$(PYTHON) gen_scenarios.py ../scenarios.json scenarios.inc

test_control_logic: test_control_logic.cpp scenarios.inc $(SRC) ../../firmware/hybrid_flow/control_logic.h
	$(CXX) $(CXXFLAGS) -o $@ test_control_logic.cpp $(SRC)

run: test_control_logic
	./test_control_logic

FW = ../../firmware/hybrid_flow
SYNTAX = $(CXX) -std=gnu++17 -Wall -Wextra -Werror -Wno-unused-parameter -fsyntax-only -Istubs
ONLINE = -Istubs/with_secrets
syntax:
	$(SYNTAX) $(ONLINE) -include Arduino.h -x c++ $(FW)/hybrid_flow.ino
	$(SYNTAX) $(ONLINE) $(FW)/sensors.cpp $(FW)/cloud.cpp $(FW)/control_logic.cpp
	$(SYNTAX) -include Arduino.h -x c++ $(FW)/hybrid_flow.ino
	$(SYNTAX) $(FW)/cloud.cpp
	$(SYNTAX) $(ONLINE) -DSIM_INPUTS=0 -include Arduino.h -x c++ $(FW)/hybrid_flow.ino
	$(SYNTAX) $(ONLINE) -DSIM_INPUTS=0 $(FW)/sensors.cpp $(FW)/cloud.cpp
	$(SYNTAX) $(ONLINE) -DWOKWI_SIM=1 -DREAL_DHT22=1 $(FW)/sensors.cpp
	$(SYNTAX) $(ONLINE) -DSIM_INPUTS=1 -include Arduino.h -x c++ $(FW)/hybrid_flow.ino
	$(SYNTAX) $(ONLINE) -DSIM_INPUTS=1 $(FW)/sensors.cpp $(FW)/cloud.cpp
	$(SYNTAX) $(ONLINE) -DREAL_SOLAR=1 -DREAL_CURRENT=1 $(FW)/sensors.cpp
	@echo "firmware compiles against the host stand-ins (bench with real sensors, all knobs, field, Wokwi and mixed profiles)"

json_check: json_check.cpp stubs/stub_impl.cpp $(FW)/cloud.cpp $(SRC)
	$(CXX) -std=gnu++17 -Wno-unused-parameter -Istubs -I$(FW) -o $@ json_check.cpp stubs/stub_impl.cpp $(FW)/cloud.cpp $(SRC)

serial-lines.txt: json_check
	./json_check > $@

clean:
	rm -f test_control_logic test_control_logic.exe scenarios.inc json_check serial-lines.txt

.PHONY: all run syntax clean
