import type { JsonObject, JsonValue } from "@elgato/utils";
import {
  SingletonAction, type Action, type DialDownEvent, type DialRotateEvent, type DialUpEvent, type DidReceiveSettingsEvent,
  type KeyDownEvent, type KeyUpEvent, type PropertyInspectorDidAppearEvent, type PropertyInspectorDidDisappearEvent, type SendToPluginEvent, type TouchTapEvent,
  type WillAppearEvent, type WillDisappearEvent,
} from "@elgato/streamdeck";
import type { Hub } from "../core/hub.js";
import type { Feedback } from "../core/strip.js";
import type { FeedbackPayload } from "@elgato/streamdeck";
import { ActionView, type ActionKind, type Surface } from "../core/views.js";
import { handlePiMessage, sendCatalog, sendPreview, sendStatus } from "./pi-bridge.js";

let theHub: Hub | null = null;
export function useHub(h: Hub): void {
  theHub = h;
}
function hub(): Hub {
  if (!theHub) throw new Error("the hub is not ready");
  return theHub;
}

/** A Stream Deck action (a key or a dial) as the SDK-free Surface the views draw on. */
function surfaceOf(a: Action<JsonObject>): Surface {
  if (a.isDial()) {
    return {
      controller: "Encoder",
      deckId: a.device.id,
      setImage: () => undefined,
      setFeedback: (fb: Feedback) => a.setFeedback(fb as FeedbackPayload),
      setTriggerDescription: (d) => a.setTriggerDescription(d),
      showAlert: () => a.showAlert(),
    };
  }
  if (a.isKey()) {
    return {
      controller: "Keypad",
      deckId: a.device.id,
      setImage: (img: string) => a.setImage(img),
      setFeedback: () => undefined,
      showAlert: () => a.showAlert(),
      showOk: () => a.showOk(),
    };
  }
  return { controller: "Keypad", deckId: "", setImage: () => undefined, setFeedback: () => undefined, showAlert: () => undefined };
}

/**
 * The SDK side of every ZIGMon action: one ActionView per visible key or dial, every event
 * handed to it, and the property inspector's messages to the bridge.
 */
export abstract class ZigmonAction extends SingletonAction<JsonObject> {
  abstract readonly kind: ActionKind;
  private readonly views = new Map<string, ActionView>();
  /** The key whose property inspector is open (it gets a live preview). */
  private piFor: string | null = null;

  private preview(id: string | null): () => string | null {
    return () => (id ? this.views.get(id)?.previewImage() ?? null : null);
  }

  override onWillAppear(ev: WillAppearEvent<JsonObject>): void {
    const old = this.views.get(ev.action.id);
    if (old) {
      old.dispose();
      hub().unwatch(old);
    }
    const v = new ActionView(this.kind, hub(), surfaceOf(ev.action), ev.payload.settings);
    this.views.set(ev.action.id, v);
    hub().watch(v);
    v.draw(true);
  }

  override onWillDisappear(ev: WillDisappearEvent<JsonObject>): void {
    const v = this.views.get(ev.action.id);
    if (!v) return;
    v.dispose();
    hub().unwatch(v);
    this.views.delete(ev.action.id);
  }

  override onDidReceiveSettings(ev: DidReceiveSettingsEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.setSettings(ev.payload.settings);
    if (this.piFor === ev.action.id) void sendPreview(this.preview(ev.action.id)).catch(() => undefined);
  }

  override onKeyDown(ev: KeyDownEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.keyDown();
  }

  override onKeyUp(ev: KeyUpEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.keyUp();
  }

  override onDialDown(ev: DialDownEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.dialDown();
  }

  override onDialUp(ev: DialUpEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.dialUp();
  }

  override onDialRotate(ev: DialRotateEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.rotate(ev.payload.ticks);
  }

  override onTouchTap(ev: TouchTapEvent<JsonObject>): void {
    this.views.get(ev.action.id)?.touch(ev.payload.hold);
  }

  override onPropertyInspectorDidAppear(ev: PropertyInspectorDidAppearEvent<JsonObject>): void {
    this.piFor = ev.action.id;
    void sendStatus(hub());
    void sendCatalog(hub(), this.kind);
    void sendPreview(this.preview(ev.action.id));
  }

  override onPropertyInspectorDidDisappear(ev: PropertyInspectorDidDisappearEvent<JsonObject>): void {
    if (this.piFor === ev.action.id) this.piFor = null;
  }

  override onSendToPlugin(ev: SendToPluginEvent<JsonValue, JsonObject>): void {
    void handlePiMessage(hub(), this.kind, ev.payload, this.preview(ev.action.id));
  }
}
