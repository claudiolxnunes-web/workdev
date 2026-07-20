import type { GraphNode, GraphEdge } from "./types";

type GraphEvents = {
  "node:created": GraphNode;
  "edge:created": GraphEdge;
};

type Handler<T> = (payload: T) => void;

export class GraphEventEmitter {
  private handlers: { [K in keyof GraphEvents]?: Handler<GraphEvents[K]>[] } = {};

  on<K extends keyof GraphEvents>(event: K, fn: Handler<GraphEvents[K]>): () => void {
    (this.handlers[event] ??= []).push(fn);
    return () => this.off(event, fn);
  }

  off<K extends keyof GraphEvents>(event: K, fn: Handler<GraphEvents[K]>): void {
    this.handlers[event] = (this.handlers[event] ?? []).filter(h => h !== fn) as any;
  }

  emit<K extends keyof GraphEvents>(event: K, payload: GraphEvents[K]): void {
    (this.handlers[event] ?? []).forEach(h => h(payload));
  }
}

export const graphEvents = new GraphEventEmitter();
