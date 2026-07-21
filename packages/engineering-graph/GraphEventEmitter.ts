import type { GraphNode, GraphEdge } from "./types.ts";

type GraphEvents = {
  "node:created": GraphNode;
  "node:updated": GraphNode;
  "node:deleted": GraphNode;
  "edge:created": GraphEdge;
  "edge:updated": GraphEdge;
  "edge:deleted": GraphEdge;
};

type Handler<T> = (payload: T) => void;

export class GraphEventEmitter {
  private handlers: { [K in keyof GraphEvents]?: Handler<GraphEvents[K]>[] } = {};

  on<K extends keyof GraphEvents>(event: K, fn: Handler<GraphEvents[K]>): () => void {
    const list = (this.handlers[event] ??= []) as Handler<GraphEvents[K]>[];
    list.push(fn);
    return () => this.off(event, fn);
  }

  off<K extends keyof GraphEvents>(event: K, fn: Handler<GraphEvents[K]>): void {
    const handlers = this.handlers[event] ?? [];
    this.handlers[event] = handlers.filter(h => h !== fn) as typeof handlers;
  }

  emit<K extends keyof GraphEvents>(event: K, payload: GraphEvents[K]): void {
    (this.handlers[event] ?? []).forEach(h => h(payload));
  }
}

export const graphEvents = new GraphEventEmitter();
