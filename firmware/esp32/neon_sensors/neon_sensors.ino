// ADXL345 FIFO bench prototype: one ESP32 per end, separate net/frame SPI sensors.
// NOT hardware validated. Pin numbers must be checked for the selected board.
#include <Arduino.h>
#include <SPI.h>
#include <esp_timer.h>
#include <esp_system.h>

#ifndef NEON_DEVICE_ID
#define NEON_DEVICE_ID 1
#endif
#ifndef NEON_GOAL_END
#define NEON_GOAL_END 0  // 0=goal_a, 1=goal_b; second board must have a distinct ID/end.
#endif

constexpr uint8_t CS[2] = {25, 26};
constexpr uint8_t IRQ[2] = {32, 33};
constexpr uint16_t PERIOD_US = 1250;  // BW_RATE 0x0D = 800Hz; never polling-labelled 1kHz.
constexpr uint16_t FIFO_OVERRUN=1, MISSING=2, SATURATED=4, TX_OVERFLOW=8,
    ESTIMATED=16, SENSOR_RESTART=32;
volatile bool pending[2] = {false, false};
uint64_t bootId, sampleSequence[2] = {0, 0}, lastStamp[2] = {0, 0};
uint32_t packetSequence[2] = {0, 0};
uint16_t sticky[2] = {0, 0};
bool present[2] = {false, false};
uint64_t heartbeat[2] = {0, 0};
SPISettings bus(1000000, MSBFIRST, SPI_MODE3);

void IRAM_ATTR netInterrupt() { pending[0]=true; }
void IRAM_ATTR frameInterrupt() { pending[1]=true; }

uint8_t readReg(uint8_t role, uint8_t reg) {
  SPI.beginTransaction(bus); digitalWrite(CS[role],LOW);
  SPI.transfer(reg|0x80); uint8_t result=SPI.transfer(0);
  digitalWrite(CS[role],HIGH); SPI.endTransaction(); return result;
}
void writeReg(uint8_t role, uint8_t reg, uint8_t value) {
  SPI.beginTransaction(bus); digitalWrite(CS[role],LOW);
  SPI.transfer(reg); SPI.transfer(value);
  digitalWrite(CS[role],HIGH); SPI.endTransaction();
}
bool configure(uint8_t role) {
  if(readReg(role,0x00)!=0xE5) return false;
  writeReg(role,0x2D,0);       // standby
  writeReg(role,0x2E,0);       // interrupts off during setup
  writeReg(role,0x31,0x0B);    // full resolution, +/-16g, four-wire SPI
  writeReg(role,0x2C,0x0D);    // normal-power 800Hz
  writeReg(role,0x38,0);       // bypass clears FIFO
  writeReg(role,0x38,0x90);    // stream FIFO, watermark 16
  writeReg(role,0x2F,0);       // watermark/overrun on INT1
  readReg(role,0x30);
  writeReg(role,0x2E,0x03);    // watermark + overrun
  writeReg(role,0x2D,0x08);    // measurement
  return readReg(role,0x2C)==0x0D && readReg(role,0x31)==0x0B;
}

// Serialize explicit little-endian bytes, never native C struct padding.
void put(uint8_t *out, size_t &n, uint64_t value, uint8_t bytes) {
  for(uint8_t i=0;i<bytes;i++) out[n++]=(value>>(8*i))&0xff;
}
uint32_t crc32(const uint8_t *data, size_t n) {
  uint32_t crc=0xffffffff;
  while(n--) { crc^=*data++; for(uint8_t b=0;b<8;b++) crc=(crc>>1)^((crc&1)?0xedb88320:0); }
  return crc^0xffffffff;
}
void packet(uint8_t role, uint8_t count, uint64_t firstTime, const int16_t raw[][3], uint16_t flags) {
  uint8_t wire[248]; size_t n=0;
  wire[n++]='N'; wire[n++]='F'; wire[n++]='S'; wire[n++]='P';
  put(wire,n,46+count*6,2);
  put(wire,n,1,1); put(wire,n,count?1:2,1); put(wire,n,NEON_GOAL_END,1); put(wire,n,role,1);
  put(wire,n,flags|sticky[role]|ESTIMATED,2); put(wire,n,NEON_DEVICE_ID,4); put(wire,n,bootId,8);
  put(wire,n,packetSequence[role]++,4); put(wire,n,sampleSequence[role],8); put(wire,n,firstTime,8);
  put(wire,n,PERIOD_US,2); put(wire,n,count,2); put(wire,n,2500,4); // assumed phase/read budget; field validation required
  for(uint8_t i=0;i<count;i++) for(uint8_t axis=0;axis<3;axis++) put(wire,n,(uint16_t)raw[i][axis],2);
  uint32_t crc=crc32(wire+4,n-4); put(wire,n,crc,4);
  // Never stall the acquisition loop waiting for serial capacity. Gaps and sticky flag expose loss.
  if(Serial.availableForWrite()>=(int)n) {
    Serial.write(wire,n); sticky[role]=0;
  } else sticky[role]|=TX_OVERFLOW;
  sampleSequence[role]+=count;
}

void drain(uint8_t role) {
  uint16_t flags=0;
  uint8_t interrupts=readReg(role,0x30);
  if(interrupts&1) flags|=FIFO_OVERRUN;
  uint8_t count=readReg(role,0x39)&0x3f;
  if(!count) return;
  if(count>=32) { count=32; flags|=FIFO_OVERRUN; }
  uint64_t now=esp_timer_get_time();
  uint64_t first=now-(count-1)*PERIOD_US; // FIFO has no per-sample hardware timestamp.
  if(lastStamp[role] && first<=lastStamp[role]) {
    // Do not invent timestamps/duplicate samples. Discard pending FIFO and require a fresh baseline.
    writeReg(role,0x38,0); writeReg(role,0x38,0x90);
    sticky[role]|=SENSOR_RESTART; sampleSequence[role]+=count; return;
  }
  int16_t raw[32][3];
  for(uint8_t i=0;i<count;i++) {
    SPI.beginTransaction(bus); digitalWrite(CS[role],LOW); SPI.transfer(0xF2); // read, burst, DATAX0
    for(uint8_t axis=0;axis<3;axis++) {
      uint8_t low=SPI.transfer(0), high=SPI.transfer(0); raw[i][axis]=(int16_t)(low|((uint16_t)high<<8));
      if(abs((int)raw[i][axis])>=3900) flags|=SATURATED;
    }
    digitalWrite(CS[role],HIGH); SPI.endTransaction();
    delayMicroseconds(5); // FIFO pop delay, including before the next FIFO_STATUS read.
  }
  lastStamp[role]=first+(count-1)*PERIOD_US;
  packet(role,count,first,raw,flags);
}

void setup() {
  Serial.setTxBufferSize(2048); Serial.begin(460800);
  SPI.begin(18,19,23);
  bootId=((uint64_t)esp_random()<<32)|esp_random(); if(!bootId) bootId=1;
  for(uint8_t role=0;role<2;role++) {
    pinMode(CS[role],OUTPUT); digitalWrite(CS[role],HIGH); pinMode(IRQ[role],INPUT);
  }
  attachInterrupt(digitalPinToInterrupt(IRQ[0]),netInterrupt,RISING);
  attachInterrupt(digitalPinToInterrupt(IRQ[1]),frameInterrupt,RISING);
  for(uint8_t role=0;role<2;role++) present[role]=configure(role);
}
void loop() {
  uint64_t now=esp_timer_get_time();
  for(uint8_t role=0;role<2;role++) {
    if(present[role] && (pending[role] || digitalRead(IRQ[role])==HIGH)) {
      pending[role]=false;
      if(readReg(role,0x00)!=0xE5) { present[role]=false; sticky[role]|=MISSING; }
      else drain(role);
    }
    if(now-heartbeat[role]>=250000) {
      heartbeat[role]=now;
      if(present[role] && readReg(role,0x00)!=0xE5) { present[role]=false; sticky[role]|=MISSING; }
      packet(role,0,now,nullptr,present[role]?0:MISSING);
      if(!present[role] && configure(role)) { present[role]=true; sticky[role]|=SENSOR_RESTART; }
    }
  }
  delay(1);
}
