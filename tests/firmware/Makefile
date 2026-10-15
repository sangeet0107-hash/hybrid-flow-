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
syntax:
	$(SYNTAX) -include Arduino.h -x c++ $(FW)/hybrid_flow.ino
	$(SYNTAX) $(FW)/sensors.cpp $(FW)/cloud.cpp $(FW)/control_logic.cpp
	$(SYNTAX) -DSIM_INPUTS=0 -include Arduino.h -x c++ $(FW)/hybrid_flow.ino
	$(SYNTAX) -DSIM_INPUTS=0 $(FW)/sensors.cpp $(FW)/cloud.cpp
	$(SYNTAX) -DWOKWI_SIM=1 -DUSE_DHT22=1 $(FW)/sensors.cpp
	@echo "firmware compiles against the host stand-ins (bench, field and Wokwi profiles)"

clean:
	rm -f test_control_logic test_control_logic.exe scenarios.inc

.PHONY: all run syntax clean
