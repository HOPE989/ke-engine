export type SseEvent = {
  event: string;
  data: Record<string, unknown>;
};

export function parseSseFrames(input: string): {
  events: SseEvent[];
  remainder: string;
} {
  const normalized = input.replaceAll("\r\n", "\n");
  const frames = normalized.split("\n\n");
  const remainder = frames.pop() ?? "";
  const events: SseEvent[] = [];

  for (const frame of frames) {
    let event = "message";
    const dataLines: string[] = [];

    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    if (dataLines.length > 0) {
      events.push({
        event,
        data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>
      });
    }
  }

  return { events, remainder };
}
