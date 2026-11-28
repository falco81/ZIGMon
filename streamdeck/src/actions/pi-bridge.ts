import streamDeck from "@elgato/streamdeck";
import type { JsonValue } from "@elgato/utils";
import type { Hub } from "../core/hub.js";
import { catalogMessage, handlePi, previewMessage, statusMessage, type Preview } from "../core/piapi.js";
import type { ActionKind } from "../core/views.js";

function send(m: unknown): Promise<void> {
  return streamDeck.ui.sendToPropertyInspector(m as JsonValue);
}

export function sendStatus(hub: Hub): Promise<void> {
  return send(statusMessage(hub));
}

export function sendCatalog(hub: Hub, kind: ActionKind): Promise<void> {
  return send(catalogMessage(hub, kind));
}

export async function handlePiMessage(hub: Hub, kind: ActionKind, payload: JsonValue, preview?: Preview): Promise<void> {
  for (const r of await handlePi(hub, kind, payload, preview)) await send(r);
}

export async function sendPreview(preview: Preview): Promise<void> {
  for (const r of previewMessage(preview)) await send(r);
}
