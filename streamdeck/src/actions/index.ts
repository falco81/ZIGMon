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
