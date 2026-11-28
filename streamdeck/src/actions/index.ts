import { action } from "@elgato/streamdeck";
import { ZigmonAction } from "./base.js";

/** 1. Any item ZIGMon allows: switch it, and on a dial turn its main value. */
@action({ UUID: "com.zigmon.streamdeck.control" })
export class ControlAction extends ZigmonAction {
  readonly kind = "control" as const;
}

/** 2. A reading, big, with its trend and a sparkline, coloured by your thresholds. */
@action({ UUID: "com.zigmon.streamdeck.reading" })
export class ReadingAction extends ZigmonAction {
  readonly kind = "reading" as const;
}

/** 3. A thermostat: turn the setpoint, push for mode/preset, touch for boost. */
@action({ UUID: "com.zigmon.streamdeck.thermostat" })
export class ThermostatAction extends ZigmonAction {
  readonly kind = "thermostat" as const;
}

/** 4. A light or dimmer: turn the brightness, push to switch it. */
@action({ UUID: "com.zigmon.streamdeck.dimmer" })
export class DimmerAction extends ZigmonAction {
  readonly kind = "dimmer" as const;
}

/** 5. Blinds: turn the position, push to stop / open / close. */
@action({ UUID: "com.zigmon.streamdeck.blinds" })
export class BlindsAction extends ZigmonAction {
  readonly kind = "blinds" as const;
}

/** 6. A scene, sequence or group of actions - one press runs it. */
@action({ UUID: "com.zigmon.streamdeck.scene" })
export class SceneAction extends ZigmonAction {
  readonly kind = "scene" as const;
}

/** 7. ZIGMon's own health: alerts, blocked addresses, the proxy, the gateway. */
@action({ UUID: "com.zigmon.streamdeck.status" })
export class StatusAction extends ZigmonAction {
  readonly kind = "status" as const;
}

// (1.3, ZIGMon 5.59.4) ten more

/** 8. The house's power now, today's kWh and a graph over 1 h / 6 h / 24 h / 7 d (a dial turns the span). */
@action({ UUID: "com.zigmon.streamdeck.power" })
export class PowerAction extends ZigmonAction {
  readonly kind = "power" as const;
}

/** 9. Network security: the alerts standing and the addresses kept out; a held press acknowledges the latest. */
@action({ UUID: "com.zigmon.streamdeck.security" })
export class SecurityAction extends ZigmonAction {
  readonly kind = "security" as const;
}

/** 10. Heating in every room: how many heat and the common mode; a press sets the next mode, or one mode, for all. */
@action({ UUID: "com.zigmon.streamdeck.heatgroup" })
export class HeatGroupAction extends ZigmonAction {
  readonly kind = "heatgroup" as const;
}

/** 11. Away / Home: the heating's away switch, and the switches turned off with it. */
@action({ UUID: "com.zigmon.streamdeck.away" })
export class AwayAction extends ZigmonAction {
  readonly kind = "away" as const;
}

/** 12. Windows and doors: how many are open, and which; red when one lets the heat out. */
@action({ UUID: "com.zigmon.streamdeck.openings" })
export class OpeningsAction extends ZigmonAction {
  readonly kind = "openings" as const;
}

/** 13. Batteries: how many are low, and the lowest. */
@action({ UUID: "com.zigmon.streamdeck.batteries" })
export class BatteriesAction extends ZigmonAction {
  readonly kind = "batteries" as const;
}

/** 14. The Zigbee network: online and offline, the one that dropped off last. */
@action({ UUID: "com.zigmon.streamdeck.zigbee" })
export class ZigbeeAction extends ZigmonAction {
  readonly kind = "zigbee" as const;
}

/** 15. A timer on a switch: on for N minutes, a press again cancels it; the countdown on the key. */
@action({ UUID: "com.zigmon.streamdeck.timer" })
export class TimerAction extends ZigmonAction {
  readonly kind = "timer" as const;
}

/** 16. A room at a glance; on a dial, its items one by one, each switched by its own rules. */
@action({ UUID: "com.zigmon.streamdeck.room" })
export class RoomAction extends ZigmonAction {
  readonly kind = "room" as const;
}

/** 17. SMS: the latest in the desktop app, a new one there, or the SMS status with mute. */
@action({ UUID: "com.zigmon.streamdeck.sms" })
export class SmsAction extends ZigmonAction {
  readonly kind = "sms" as const;
}

/** 18. A value ZIGMon computes over the house (the total power, the lights on, the coldest room...), shown as a Reading. */
@action({ UUID: "com.zigmon.streamdeck.computed" })
export class ComputedAction extends ZigmonAction {
  readonly kind = "computed" as const;
}
