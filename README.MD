# Spatial Pedagogy

## Terminal commands

### To build the executable
```bash
pio run
```

### To upload it in the esp32
```bash
pio run --target upload
```

### To monitor the prints of the device
```bash
pio device monitor
```

## Code modifications to make the devices work

In the DW1000 original library, it does not support having a 5th anchor connected to a tag.
We have to manually change the library code to adapt it to our case. We need to modify 2 different files :

### DW1000/src/DW1000.cpp
    At the line 172, there is the line 

```cpp
    #ifndef ESP8266
```

in the begin function and we have to put

```cpp
    #ifdef ESP8266
```

instead.

### DW1000/src/DW1000Ranging.cpp

Add a check if we can add the new device in the array before doing it. (line 243)

```cpp
	if(_networkDevicesNumber + 1 <= MAX_DEVICES && addDevice)
```

## Phone details

### PIN
1545

## TODO

### Antenna delays

When I did my precision 1d, the server goes timeout becuase it doesnt receive anything from the Tag but
its because there are no anchors not because we lost connection to the Tag.... we probably want to fix it

