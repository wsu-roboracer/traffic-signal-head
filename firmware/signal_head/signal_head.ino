/*
 * 1/10 scale traffic signal head - 3 x 12 LED rings
 *
 * Drives the signal-head LED board through a ULN2003A (or three 2N7000s)
 * switching the low side of each ring. A HIGH on an output pin lights that
 * ring; the board's common anode sits on VLED.
 *
 *   Arduino          ULN2003A          LED board J1
 *   D2  ----------->  IN1  OUT1 ----->  2  K_RED
 *   D3  ----------->  IN2  OUT2 ----->  3  K_AMB
 *   D4  ----------->  IN3  OUT3 ----->  4  K_GRN
 *   GND ----------->  GND                1  VLED  <--- +9 V
 *
 * Mode button: momentary switch from D5 to GND. Uses the AVR's internal
 * pull-up, so no external resistor. Each press steps:
 *
 *   CYCLE -> RED -> AMBER -> GREEN -> CYCLE ...
 *
 * The three lock modes hold one ring on solid, which is what you want on the
 * bench: pick a colour, leave it, and go measure current or check the diffuser
 * without waiting for a phase to come around.
 */

/* Set to 1 to have the board come back up in whatever mode it was left in.
 * Handy mid-test session; leave at 0 for a demo piece so it always powers on
 * into the normal cycle. */
#define REMEMBER_MODE 0

#if REMEMBER_MODE
#include <EEPROM.h>
const int EE_ADDR = 0;
#endif

const uint8_t PIN_RED = 2;
const uint8_t PIN_AMB = 3;
const uint8_t PIN_GRN = 4;
const uint8_t PIN_BTN = 5;

enum Mode  : uint8_t { MODE_CYCLE, MODE_RED, MODE_AMB, MODE_GRN, MODE_COUNT };
enum Phase : uint8_t { P_GREEN, P_AMBER, P_RED, PHASE_COUNT };

/* Compressed from real signal timing so a viewer sees a full cycle. Yellow is
 * held at a realistic 4 s - real yellows are computed from approach speed and
 * are almost never outside 3-5 s. */
const unsigned long PHASE_MS[PHASE_COUNT] = {
  15000UL,   /* P_GREEN */
   4000UL,   /* P_AMBER */
  19000UL    /* P_RED   */
};

const unsigned long DEBOUNCE_MS = 30;

Mode  mode  = MODE_CYCLE;
Phase phase = P_RED;
unsigned long phaseStart = 0;

/* button debounce state */
bool lastReading = HIGH;
bool stableState = HIGH;
unsigned long lastEdge = 0;

static void applyOutputs()
{
  bool r = false, a = false, g = false;

  switch (mode) {
    case MODE_RED: r = true; break;
    case MODE_AMB: a = true; break;
    case MODE_GRN: g = true; break;
    default:
      r = (phase == P_RED);
      a = (phase == P_AMBER);
      g = (phase == P_GREEN);
      break;
  }

  digitalWrite(PIN_RED, r);
  digitalWrite(PIN_AMB, a);
  digitalWrite(PIN_GRN, g);
}

static void setMode(Mode m)
{
  mode = m;

  /* Re-enter the cycle at a known point rather than wherever it was abandoned,
   * so stepping back into CYCLE always gives the same predictable sequence. */
  if (m == MODE_CYCLE) {
    phase = P_RED;
    phaseStart = millis();
  }

#if REMEMBER_MODE
  EEPROM.update(EE_ADDR, (uint8_t)m);
#endif

  applyOutputs();
}

void setup()
{
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_AMB, OUTPUT);
  pinMode(PIN_GRN, OUTPUT);
  pinMode(PIN_BTN, INPUT_PULLUP);

#if REMEMBER_MODE
  uint8_t saved = EEPROM.read(EE_ADDR);
  mode = (saved < MODE_COUNT) ? (Mode)saved : MODE_CYCLE;
#endif

  phase = P_RED;
  phaseStart = millis();
  stableState = lastReading = digitalRead(PIN_BTN);
  applyOutputs();
}

void loop()
{
  unsigned long now = millis();

  /* Debounced press detection. A press is a settled HIGH->LOW transition,
   * since the switch pulls the pin to ground. */
  bool reading = digitalRead(PIN_BTN);
  if (reading != lastReading) {
    lastEdge = now;
    lastReading = reading;
  }
  if ((now - lastEdge) >= DEBOUNCE_MS && reading != stableState) {
    stableState = reading;
    if (stableState == LOW) {
      setMode((Mode)((mode + 1) % MODE_COUNT));
    }
  }

  /* Advance the cycle only when not locked. Subtracting unsigned millis()
   * this way stays correct across the ~49 day rollover. */
  if (mode == MODE_CYCLE && (now - phaseStart) >= PHASE_MS[phase]) {
    switch (phase) {
      case P_GREEN: phase = P_AMBER; break;
      case P_AMBER: phase = P_RED;   break;
      default:      phase = P_GREEN; break;
    }
    phaseStart = now;
    applyOutputs();
  }
}
